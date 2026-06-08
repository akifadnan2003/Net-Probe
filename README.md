# NetProbe

**UDP-Based Reliable File Transfer, Traffic Monitoring and Network Performance Analysis Platform**

Bursa Teknik Üniversitesi – Bilgisayar Ağları Dönem Projesi

GitHub: _add your link here_

---

## Project Overview

NetProbe implements a reliable file-transfer protocol **on top of raw UDP sockets** — no TCP, no ready-made transfer libraries.  Reliability mechanisms (sequence numbers, ACKs, timeouts, retransmission, duplicate detection, file-integrity check) are built entirely at the application layer.  A logging + analysis module records every network event and produces performance graphs.

---

## File Structure

```
netprobe/
├── protocol.py          # Binary packet format (DATA / ACK / FIN / FIN-ACK)
├── server.py            # UDP server – receive file, send ACKs, verify integrity
├── client.py            # UDP client – split & send file, handle timeouts/retransmits
├── logger.py            # CSV event logger used by both client and server
├── analyzer.py          # Compute metrics and produce matplotlib graphs
├── experiments.py       # Automated experiment runner (all 4 scenarios + bonus)
├── generate_test_files.py
├── logs/                # Per-run CSV event logs (auto-created)
├── received/            # Files reconstructed by server (auto-created)
├── results/             # PNG plots + summary CSV (auto-created)
└── test_data/           # Input test files (created by generate_test_files.py)
```

---

## Requirements

```
pip install matplotlib pandas
```

Python ≥ 3.8.  No other external dependencies (uses only stdlib: `socket`, `struct`, `zlib`, `hashlib`, `threading`, `csv`, `argparse`).

---

## Quick Start

### 1. Generate test files
```bash
python generate_test_files.py
```

### 2. Start the server (terminal 1)
```bash
python server.py --port 9999 --loss 0.0
```

### 3. Send a file (terminal 2)
```bash
python client.py test_data/file_256k.bin --port 9999 --chunk 1024 --timeout 1.0
```

### 4. Run all experiments automatically
```bash
python experiments.py
```
This runs scenarios 1–4 plus the sliding-window bonus, saves graphs to `results/`, and writes `results/summary.csv`.

---

## Configuration Parameters

| Parameter | Default | Description |
|-----------|---------|-------------|
| `--chunk` | 1024 B | Payload size per packet |
| `--timeout` | 1.0 s | ACK wait timeout before retransmit |
| `--loss` | 0.0 | Simulated packet drop probability [0, 1) |
| `--window` | 1 | Sliding window size (1 = Stop-and-Wait) |
| `MAX_RETRIES` | 5 | Max retransmissions per packet (in `protocol.py`) |

---

## Protocol Design

### Packet Formats (big-endian binary)

| Field | Size | Notes |
|-------|------|-------|
| **DATA** | | |
| type | 1 B | `0x01` |
| seq | 4 B | Sequence number (0-indexed) |
| total | 4 B | Total packet count for this transfer |
| payload_len | 2 B | Actual payload bytes in this packet |
| crc32 | 4 B | CRC-32 of payload (corruption detection) |
| payload | ≤ chunk_size B | File data |
| **ACK** | | |
| type | 1 B | `0x02` |
| ack_num | 4 B | Sequence number being acknowledged |
| crc32 | 4 B | CRC-32 of ack_num field |
| **FIN** | | |
| type | 1 B | `0x03` |
| crc32 | 4 B | CRC-32 of MD5 field |
| md5_hex | 32 B | MD5 hash of the complete file (ASCII) |
| **FIN-ACK** | | |
| type | 1 B | `0x04` |
| status | 1 B | `1` = integrity OK, `0` = failed |

### Reliability Mechanisms

1. **Sequence numbers** – every DATA packet carries `seq` (0 … total-1).
2. **ACK** – server sends individual ACK for each correctly received packet.
3. **Timeout** – client waits `timeout` seconds; if no ACK, retransmits.
4. **Retransmission** – up to `MAX_RETRIES = 5` attempts per packet (configurable).
5. **Duplicate detection** – server tracks received seq numbers; duplicate DATA triggers a re-ACK but the payload is **not** written again.
6. **File integrity** – after all DATA, client sends FIN with MD5 of the original file; server recomputes MD5 of reassembled data and replies FIN-ACK(OK/FAIL).

### Transfer Flow

```
Client                             Server
  │── DATA(seq=0) ──────────────►  │
  │◄─────────────────── ACK(0) ──  │
  │── DATA(seq=1) ──────────────►  │
  │        ✗ (lost / timeout)      │
  │── DATA(seq=1) [retry] ───────► │  ← retransmission
  │◄─────────────────── ACK(1) ──  │
  │         ...                    │
  │── FIN(md5) ─────────────────►  │
  │◄──────────────── FIN-ACK(OK) ─ │
```

---

## Experiment Scenarios

| # | Variable | Fixed | Purpose |
|---|----------|-------|---------|
| 1 | Chunk/packet size (128 – 4096 B) | 512 KB, 0% loss | Throughput vs fragmentation overhead |
| 2 | Timeout (0.1 – 4.0 s) | 256 KB, 5% loss | Optimal timeout vs unnecessary retransmissions |
| 3 | Loss rate (0 – 20%) | 256 KB, 1 KB chunk | Goodput degradation under lossy network |
| 4 | File size (32 KB – 1 MB) | 1 KB chunk, 0% loss | System efficiency at scale |
| BONUS | Window size (1 – 16) | 512 KB, 0% loss | Stop-and-Wait vs Sliding Window throughput |

---

## Performance Metrics

| Metric | Formula |
|--------|---------|
| **Throughput** | `(packets_sent × chunk_size) / duration` |
| **Goodput** | `file_size / duration` |
| **Retransmission rate** | `retransmissions / packets_sent` |
| **Packet loss rate** | `failed_packets / total_packets` |
| **Avg RTT** | Mean of per-packet (ACK_time − SEND_time) |
| **Completion time** | Wall-clock from first SEND to FIN-ACK |

---

## Bonus Features Implemented

- **Sliding Window (Go-Back-N style)** – `--window N` enables window of N in-flight packets; background thread collects ACKs.
- **Packet loss simulator** – `--loss 0.1` randomly drops 10% of outgoing (client) or incoming (server) packets, enabling experiments without a lossy network.

---

## Group Task Division

| Member | Responsibility |
|--------|---------------|
| _name_ | protocol.py, server.py |
| _name_ | client.py, logger.py |
| _name_ | analyzer.py, experiments.py, report |

---

## Known Limitations

- Stop-and-wait is efficient only on loopback; use `--window 8` or higher for LAN/WAN.
- Loss simulator operates independently on client and server sides; combined effective loss may be slightly different from configured rate.
- No flow control or congestion control beyond retransmission.
