"""
NetProbe – Web Dashboard (Flask)

Usage:
  pip install flask
  python app.py
  open http://localhost:5000
"""

import os, sys, json, time, queue, threading, ast, subprocess, csv as _csv
from flask import (Flask, render_template, request, Response,
                   jsonify, send_from_directory)

app = Flask(__name__)
BASE = os.path.dirname(os.path.abspath(__file__))

os.makedirs(os.path.join(BASE, 'uploads'), exist_ok=True)
os.makedirs(os.path.join(BASE, 'results'), exist_ok=True)
os.makedirs(os.path.join(BASE, 'logs'),    exist_ok=True)

_server_state    = {'running': False, 'port': None}
_active_transfers = {}   # tid -> {queue, done, result}


# ── Static pages ──────────────────────────────────────────────────────────────

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/results/<path:filename>')
def serve_result(filename):
    return send_from_directory(os.path.join(BASE, 'results'), filename)


# ── File management ───────────────────────────────────────────────────────────

@app.route('/api/files')
def list_files():
    files = []
    for d in ['test_data', 'uploads']:
        full = os.path.join(BASE, d)
        if os.path.isdir(full):
            for f in sorted(os.listdir(full)):
                p = os.path.join(full, f)
                if os.path.isfile(p):
                    files.append({'name': f'{d}/{f}',
                                  'size': os.path.getsize(p)})
    return jsonify(files)

@app.route('/api/upload', methods=['POST'])
def upload():
    f = request.files.get('file')
    if not f:
        return jsonify({'ok': False, 'msg': 'No file'}), 400
    dest = os.path.join(BASE, 'uploads', f.filename)
    f.save(dest)
    return jsonify({'ok': True, 'path': f'uploads/{f.filename}',
                    'size': os.path.getsize(dest)})


# ── Server control ────────────────────────────────────────────────────────────

@app.route('/api/server/status')
def server_status():
    return jsonify(_server_state)

@app.route('/api/server/start', methods=['POST'])
def server_start():
    d    = request.get_json(force=True)
    port = int(d.get('port', 9999))
    loss = float(d.get('loss', 0.0))
    if _server_state['running']:
        return jsonify({'ok': False, 'msg': 'Already running'})

    def _run():
        sys.path.insert(0, BASE)
        from server import run_server
        _server_state.update(running=True, port=port)
        run_server('0.0.0.0', port, os.path.join(BASE, 'received'),
                   loss, os.path.join(BASE, f'logs/web_srv_{port}.csv'))
        _server_state['running'] = False

    threading.Thread(target=_run, daemon=True).start()
    time.sleep(0.25)
    return jsonify({'ok': True})

@app.route('/api/server/stop', methods=['POST'])
def server_stop():
    _server_state['running'] = False
    return jsonify({'ok': True})


# ── Transfer ──────────────────────────────────────────────────────────────────

@app.route('/api/transfer/start', methods=['POST'])
def transfer_start():
    d = request.get_json(force=True)
    filepath    = os.path.join(BASE, d.get('file', 'test_data/file_32k.bin'))
    host        = d.get('host', '127.0.0.1')
    port        = int(d.get('port', 9999))
    timeout     = float(d.get('timeout', 1.0))
    chunk_size  = int(d.get('chunk', 1024))
    loss_rate   = float(d.get('loss', 0.0))
    window_size = int(d.get('window', 1))
    crypto_mode = d.get('mode', 'none')
    crypto_key  = d.get('key', '')

    tid      = f't{int(time.time()*1000)}'
    q        = queue.Queue()
    log_path = os.path.join(BASE, f'logs/web_{tid}.csv')
    _active_transfers[tid] = {'queue': q, 'done': False, 'result': None}

    def _run():
        result_box = [None]

        def do_transfer():
            sys.path.insert(0, BASE)
            from client import send_file
            result_box[0] = send_file(
                filepath, host, port, timeout, chunk_size,
                loss_rate, window_size, log_path, crypto_mode, crypto_key)

        tx = threading.Thread(target=do_transfer, daemon=True)
        tx.start()

        # tail log and push each event to the SSE queue
        while not os.path.exists(log_path):
            time.sleep(0.05)
        with open(log_path, 'r', encoding='utf-8') as lf:
            lf.readline()   # skip CSV header
            while True:
                line = lf.readline()
                if line:
                    try:
                        row = next(_csv.reader([line]))
                    except StopIteration:
                        continue
                    if len(row) == 4:
                        ts_s, ev, seq_s, det_s = row
                        try:
                            det = ast.literal_eval(det_s)
                            if not isinstance(det, dict):
                                det = {'value': det_s}
                        except Exception:
                            det = {'raw': det_s[:60]}
                        q.put({'ts': ts_s, 'event': ev,
                               'seq': seq_s, 'details': det})
                        if ev == 'TRANSFER_COMPLETE':
                            break
                else:
                    if not tx.is_alive():
                        break
                    time.sleep(0.02)

        tx.join(timeout=5)
        _active_transfers[tid]['result'] = result_box[0]
        _active_transfers[tid]['done']   = True
        q.put({'event': '__done__', 'result': result_box[0]})

    threading.Thread(target=_run, daemon=True).start()
    return jsonify({'ok': True, 'id': tid})


@app.route('/api/transfer/stream/<tid>')
def transfer_stream(tid):
    def gen():
        if tid not in _active_transfers:
            yield f"data: {json.dumps({'event': 'error'})}\n\n"
            return
        rec = _active_transfers[tid]
        while True:
            try:
                evt = rec['queue'].get(timeout=30)
                yield f"data: {json.dumps(evt)}\n\n"
                if evt.get('event') == '__done__':
                    break
            except queue.Empty:
                yield "data: {\"event\":\"__hb__\"}\n\n"

    return Response(gen(), mimetype='text/event-stream',
                    headers={'Cache-Control': 'no-cache',
                             'X-Accel-Buffering': 'no'})


# ── Results / Experiments ─────────────────────────────────────────────────────

@app.route('/api/results/images')
def result_images():
    rdir = os.path.join(BASE, 'results')
    imgs = sorted(f for f in os.listdir(rdir) if f.endswith('.png')) \
           if os.path.isdir(rdir) else []
    return jsonify(imgs)

@app.route('/api/experiments/run', methods=['POST'])
def run_experiments():
    def gen():
        proc = subprocess.Popen(
            [sys.executable, os.path.join(BASE, 'experiments.py')],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, bufsize=1, cwd=BASE)
        for line in proc.stdout:
            yield f"data: {json.dumps({'line': line.rstrip()})}\n\n"
        proc.wait()
        yield f"data: {json.dumps({'done': True, 'rc': proc.returncode})}\n\n"

    return Response(gen(), mimetype='text/event-stream',
                    headers={'Cache-Control': 'no-cache',
                             'X-Accel-Buffering': 'no'})

@app.route('/api/tcp_compare', methods=['POST'])
def run_tcp_compare():
    d    = request.get_json(force=True)
    fpath = os.path.join(BASE, d.get('file', 'test_data/file_128k.bin'))

    def gen():
        sys.path.insert(0, BASE)
        from tcp_compare import run_comparison
        import io, contextlib
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            result = run_comparison(fpath)
        for line in out.getvalue().splitlines():
            yield f"data: {json.dumps({'line': line})}\n\n"
        payload = json.dumps({'done': True, 'result': {
            'tcp_goodput':  result['tcp']['goodput'],
            'udp_goodput':  result['udp']['goodput'],
            'tcp_duration': result['tcp']['duration'],
            'udp_duration': result['udp']['duration'],
        }})
        yield f"data: {payload}\n\n"

    return Response(gen(), mimetype='text/event-stream',
                    headers={'Cache-Control': 'no-cache',
                             'X-Accel-Buffering': 'no'})


if __name__ == '__main__':
    print('[NetProbe] Dashboard: http://localhost:5000')
    app.run(host='0.0.0.0', port=5000, debug=False, threaded=True)
