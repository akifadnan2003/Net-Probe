# NetProbe – Sunum & Mastery Rehberi
## Her Soruya Hazır Ol | BTU Bilgisayar Ağları Dönem Projesi

---

## BÖLÜM 1 – Sunum Yapısı (10 dakika)

### Slayt 1 – Başlık
**NetProbe: UDP Tabanlı Güvenilir Dosya Aktarımı, Trafik İzleme ve Performans Analizi**
- İsim, öğrenci no, tarih

### Slayt 2 – Projenin Amacı (30 sn)
"Bu projede UDP'nin güvenilir olmayan yapısı üzerine, TCP'ye benzer güvenilirlik mekanizmalarını
uygulama katmanında sıfırdan tasarladık. Amaç, protokol tasarımının detaylarını uygulamalı öğrenmek."

### Slayt 3 – Sistem Mimarisi (1 dk)
```
[CLIENT]                           [SERVER]
  │── DATA(seq, payload, crc) ──►    │
  │◄──────────────── ACK(seq) ──     │
  │  [timeout → retransmit]          │
  │── FIN(MD5) ────────────────►     │
  │◄──────────── FIN-ACK(OK) ──      │
```
- UDP socket programming: `socket.SOCK_DGRAM`
- İstemci → gönderici; Sunucu → alıcı + bütünlük doğrulayıcı

### Slayt 4 – Protokol Tasarımı (2 dk)
**Paket formatı (ikili / binary):**

| Alan | Boyut | Açıklama |
|------|-------|----------|
| type | 1 B | 0x01=DATA, 0x02=ACK, 0x03=FIN, 0x04=FIN-ACK |
| seq | 4 B | Sıra numarası |
| total | 4 B | Toplam paket sayısı |
| payload_len | 2 B | Gerçek veri uzunluğu |
| crc32 | 4 B | Bozulma tespiti (zlib.crc32) |
| payload | ≤1024 B | Dosya verisi |

**Güvenilirlik mekanizmaları:**
1. Sequence number → sıralı birleştirme, kayıp tespiti
2. ACK → her paket için bireysel onay
3. Timeout (varsayılan: 1 sn) → ACK gelmezse yeniden gönder
4. Max 5 yeniden deneme → başarısızsa log'a yaz
5. Duplicate detection → sunucu zaten alınanları set'te tutar, ACK gönderir ama yazmaz
6. MD5 hash → aktarım sonunda dosya bütünlüğü doğrulanır

### Slayt 5 – Trafik İzleme (1 dk)
Her event `logs/client_log.csv`'e kaydedilir:
```
timestamp,event,seq,details
1780750528.1,PACKET_SENT,0,{'attempt':0}
1780750528.2,ACK_RECEIVED,0,{'rtt':'0.000124'}
1780750535.1,TIMEOUT,5,{'attempt':1}
1780750536.2,PACKET_SENT,5,{'attempt':1}
...
1780750600.0,TRANSFER_COMPLETE,-1,{'duration':'7.050','goodput':'4654.2',...}
```

### Slayt 6 – Demo (2 dk)
Terminalde canlı göster:
```bash
# Terminal 1
python server.py --port 9999 --loss 0.1

# Terminal 2
python client.py test_data/file_256k.bin --port 9999 --loss 0.1 --timeout 1.0
```
"Gördüğünüz gibi paket kayıpları timeout'a yol açıyor, sistem otomatik olarak yeniden gönderiyor
ve dosya bütünlüğü MD5 ile doğrulanıyor."

### Slayt 7 – Deney Sonuçları (2 dk)
**Senaryo 1 – Paket boyutunun etkisi:**
- Küçük paketler (128B): yüksek header overhead → düşük throughput
- Büyük paketler (4096B): az paket, az overhead → yüksek throughput
- Optimal nokta: ~1024–2048B

**Senaryo 2 – Timeout değerinin etkisi:**
- Çok küçük timeout (0.1s): gereksiz retransmission → goodput düşüyor
- Çok büyük timeout (4s): loss'ta uzun bekleme → completion time artıyor
- Optimal: RTT'ye yakın bir değer (loopback'te ~0.5s)

**Senaryo 3 – Kayıp oranının etkisi:**
- 0% loss: goodput ≈ throughput
- 10% loss: retransmission rate %14+ → goodput belirgin düşüş
- 20% loss: sistem büyük ölçüde yavaşlıyor

**Senaryo 4 – Dosya boyutunun etkisi:**
- Küçük dosyalarda bağlantı kurma overhead oranı yüksek
- Büyük dosyalarda sabit overhead amortize olur → daha verimli

### Slayt 8 – Bonus: Sliding Window
- `--window 1` = Stop-and-Wait (her paket için ACK bekle)
- `--window 8` = 8 paket aynı anda uçuşta → ~8x daha yüksek throughput (0% loss'ta)
- Implementasyon: ayrı bir `threading.Thread` ACK alır, ana thread gönderir

### Slayt 9 – Sonuç
- UDP üzerinde TCP-benzeri güvenilirlik sıfırdan tasarlandı
- Stop-and-Wait + Sliding Window implementasyonu
- Kapsamlı loglama ve otomatik grafik üretimi
- 4 deney senaryosu + bonus karşılaştırma

---

## BÖLÜM 2 – Beklenen Sorular ve Kesin Cevaplar

### TEMEL KAVRAMLAR

**S: UDP ile TCP arasındaki temel fark nedir?**
> TCP: bağlantı odaklı (connection-oriented), güvenilir, sıralı, akış kontrolü ve tıkanıklık kontrolü var.
> UDP: bağlantısız (connectionless), güvenilir değil, sıralama yok, kontrol mekanizması yok.
> UDP daha hızlı ve daha az overhead'li ama "at-unut" (fire-and-forget) yapısındadır.
> Bu projede UDP'nin üzerine TCP'nin güvenilirlik mekanizmalarını uygulama katmanında ekledik.

**S: Neden UDP'yi kullandınız, doğrudan TCP kullansaydınız olmaz mıydı?**
> Proje amacı güvenilirlik mekanizmalarını *kendimiz* tasarlamaktı. TCP'yi kullanmak bu öğrenmeyi engellerdi.
> Ayrıca özel protokol tasarlayabilmek; streaming, gaming, DNS gibi alanlarda önemlidir — bunlar da UDP üzerinde çalışır.

**S: Sequence number ne işe yarar?**
> İki işlevi var:
> 1. Kayıp tespiti: ACK gelmezse hangi paketi yeniden göndereceğimizi biliriz.
> 2. Sıralı birleştirme: Paketler farklı sırada gelebilir (UDP garantisi yok), seq numarasıyla doğru sıraya koyarız.
> Bizim implementasyonumuzda seq = 0'dan (total-1)'e kadar gider; sunucu `received[seq] = payload` dict'ine yazar.

**S: ACK mekanizması nasıl çalışır?**
> Sunucu her DATA paketini alınca `ACK(seq)` paketi gönderir.
> İstemci her paket gönderdiğinde timeout süresi kadar ACK bekler.
> ACK gelirse bir sonraki pakete geçer; gelmezse paketi yeniden gönderir.
> Bizde bireysel ACK (individual ACK) var, yani her paket için ayrı onay.

**S: Timeout değerini nasıl belirlediniz?**
> Teorik olarak timeout ≥ RTT (Round-Trip Time) + işlem süresi olmalıdır.
> Loopback'te RTT ~0.1ms, LAN'da ~1-5ms, WAN'da ~50-200ms.
> Biz varsayılan 1 saniye seçtik — loopback için fazla ama gerçek ağlarda da çalışır.
> Senaryo 2'de farklı timeout değerlerinin etkisini gösterdik: küçük timeout gereksiz retransmission'a yol açar.

**S: Retransmission mekanizması nasıl çalışır?**
> İstemci timeout dolduğunda aynı paketi (aynı seq number ile) tekrar gönderir.
> Maksimum 5 deneme (MAX_RETRIES=5, `protocol.py`'de yapılandırılabilir).
> 5 denemeden sonra da ACK gelmezse o paket başarısız sayılır, log'a yazılır, aktarım devam eder.

**S: Duplicate paket durumunda ne oluyor?**
> Sunucu `received` adında bir Python `dict` (set gibi kullanıyoruz) tutar.
> Eğer gelen paketin seq numarası dict'te varsa: veri yazmaz, ama ACK'i yine de gönderir.
> Neden ACK gönderiyoruz? İstemci ACK'i almamış olabilir, ACK göndermezsek istemci tekrar gönderir — sonsuz döngü.

**S: Dosya bütünlüğünü nasıl doğruluyorsunuz?**
> İstemci dosyayı göndermeden önce MD5 hash'ini hesaplar (Python `hashlib.md5`).
> Tüm paketler gittikten sonra FIN paketinde bu MD5'i sunucuya gönderir.
> Sunucu parçaları birleştirip kendi MD5'ini hesaplar ve karşılaştırır.
> Eşleşirse FIN-ACK(OK=1), eşleşmezse FIN-ACK(OK=0) döner.

**S: Checksum ile hash farkı nedir? İkisini neden birlikte kullandınız?**
> **CRC-32** (paket başlığında): her pakette bireysel bozulma tespiti. Küçük, hızlı.
> **MD5** (FIN paketinde): tüm dosyanın end-to-end bütünlüğü. Paketler doğru sırada ve eksiksiz birleşti mi?
> CRC-32 tek paketi korur; MD5 tüm aktarımı korur.

---

### GÜVENİLİR AKTARIM MEKANİZMALARI

**S: Stop-and-Wait ile Sliding Window farkı?**
> **Stop-and-Wait**: Bir paket gönder, ACK bekle, sonra bir sonrakini gönder.
>   - Basit, hata tespiti kolay
>   - Verimsiz: ACK beklerken kanal boşta kalır
>   - Utilization = RTT süresinin sadece küçük bir kısmında aktif
>
> **Sliding Window**: W tane paket ACK beklemeden gönderilebilir (pipeline).
>   - W=8 olunca teorik olarak 8x daha fazla throughput
>   - Karmaşık: sıra dışı ACK yönetimi gerekir
>   - Bizde `--window N` ile etkinleştirilir

**S: Go-Back-N ve Selective Repeat farkı?**
> **Go-Back-N**: Kayıp olan paketten itibaren hepsini yeniden gönder (penceredeki tüm paketleri).
>   - Basit receiver: sıra dışı paket gelirse atar
>   - Yüksek retransmission overhead
>
> **Selective Repeat**: Sadece kaybolan paketi yeniden gönder.
>   - Receiver sıra dışı paketleri tamponlar
>   - Daha verimli, daha karmaşık
>   - Bizim sliding window implementasyonumuz SR'a yakın (bireysel timer per paket)

**S: Sliding Window implementasyonunuzu anlatır mısınız?**
> `client.py`'de `_send_sliding_window()` fonksiyonu:
> - Ana thread: window içindeki paketleri gönderir, timer kontrol eder
> - `ack_receiver` thread'i: arka planda ACK'leri okur, `acked` set'ine ekler
> - `threading.Lock` ile shared state korunur
> - `base` değişkeni: window'un sol sınırı (en eski unACKed paket)
> - Timer: her pakete `send_time[seq]` kaydedilir, timeout geçmişse retransmit

---

### PERFORMANS METRİKLERİ

**S: Throughput nedir ve nasıl hesaplandı?**
> Throughput = Kanala gönderilen toplam byte / Süre
> Retransmission'ları da içerir. Fiziksel kanal kullanımını gösterir.
> `throughput = (sent_packets × chunk_size) / duration`

**S: Goodput nedir, throughput'tan farkı?**
> Goodput = Kullanıcıya iletilen faydalı veri / Süre = `file_size / duration`
> Throughput ≥ Goodput her zaman. Fark = retransmission + header overhead.
> Yüksek kayıp oranında: throughput sabit kalabilir ama goodput düşer (aynı bandwidt'i tekrar göndermek için kullanıyoruz).

**S: RTT (Round-Trip Time) nasıl ölçüldü?**
> Her paket için: `rtt = ack_received_time - packet_sent_time`
> Log'a kaydedilir: `ACK_RECEIVED, seq=5, rtt=0.000124`
> Sonunda ortalama, min, max RTT hesaplanır.

**S: Retransmission rate nasıl hesaplandı?**
> `retrans_rate = retransmissions / packets_sent`
> 0% loss'ta: 0.00%
> 10% loss ile testimizde: ~14% (çünkü hem client hem server %10 drop → ~%19 efektif kayıp)

---

### SİSTEM MİMARİSİ

**S: server.py'de `serve_once()` neden?**
> Her deney senaryosu için server'ı yeniden başlatmak yerine, tek bir transferi handle eden
> ve dönen fonksiyon. `experiments.py` bunu thread olarak çalıştırır.

**S: Loglama neden CSV?**
> CSV: pandas/Excel ile kolayca analiz edilir. Her satır = bir network event.
> Timestamp, event tipi, seq numarası, detaylar. `analyzer.py` bu CSV'yi okuyarak grafik üretir.

**S: Binary paket formatı neden struct ile yapıldı?**
> `struct.pack('!B I I H I', ...)` — `!` big-endian (network byte order).
> JSON veya string encoding'e göre çok daha verimli: 15 byte header vs JSON'da onlarca byte.
> Ayrıca gerçek ağ protokollerinin çalışma şekliyle birebir örtüşüyor.

**S: Neden `socket.SOCK_DGRAM`?**
> UDP socket tipi. `SOCK_STREAM` = TCP. DGRAM = datagram (paket odaklı, connectionless).

---

### DENEYSEL SORULAR

**S: Paket boyutunu büyütünce throughput neden artar?**
> Sabit overhead (header: 15 byte) daha büyük payload'a bölündüğünde oranı düşer.
> 128B payload: %11 overhead. 4096B payload: %0.36 overhead.
> Ayrıca daha az paket = daha az ACK round-trip = daha az bekleme.
> AMA: çok büyük paketler IP fragmentation'a neden olabilir (MTU=1500B), bu da kayıp riskini artırır.

**S: Timeout çok küçük olunca ne olur?**
> ACK henüz gelmeden timeout olur → gereksiz retransmission.
> Karşı taraf duplicate alır ama atar (duplicate detection sayesinde dosya bozulmaz).
> Retransmission rate artar, goodput düşer, ağ gereksiz yüklenir.

**S: Loss rate artınca goodput neden düşer?**
> Her kayıp paket için: `timeout süresi` kadar bekle + retransmit.
> Stop-and-wait'te bir paketin kaybı tüm aktarımı bekletir.
> 10% loss → ortalama her 10 pakette bir timeout (1s) = ciddi gecikme.

**S: Sliding window neden daha hızlı?**
> Stop-and-wait utilization = `L/R / (L/R + RTT)` ≈ çok düşük loopback dışında.
> Window=8: 8 paket "uçuşta" → boru hattı dolar → kanal daha verimli kullanılır.
> RTT=10ms, paket gönderme süresi=0.1ms → S&W utilization = %1, W=8 ile %8.

---

### ZOR SORULAR (Hocanın favorileri)

**S: UDP üzerinde TCP implementasyonu yaptınız diyebilir misiniz?**
> Hayır, tam TCP değil. TCP'nin bazı özelliklerini (seq, ACK, retransmit) uyguladık ama:
> - Congestion control (AIMD, slow start) yok
> - Flow control (receiver window) yok
> - 3-way handshake connection setup yok
> - Byte-stream yerine paket-tabanlı uygulama katmanı protokolü tasarladık.

**S: Eğer ACK paketi kaybolursa ne olur?**
> İstemci timeout yaşar ve paketi yeniden gönderir.
> Sunucu bu paketi daha önce almıştır (received dict'te var) → duplicate detection devreye girer.
> Sunucu ACK'i tekrar gönderir ama veriyi yazmaz. Sistem doğru çalışmaya devam eder.

**S: Aynı anda 100 paket kaybedilirse ne olur?**
> Her paket için en fazla 5 deneme var (toplam 6 gönderim).
> Her timeout 1 saniye → 5 timeout = 5 saniye bekleme o paket için.
> 100 paket kaybı → stop-and-wait'te sıralı, 500 saniyeye kadar çıkabilir!
> Sliding window'da paralel retry mümkün, süre daha kısa.
> Failed_packets sayacı artar ve log'a yazılır.

**S: Neden MD5 kullandınız, SHA-256 daha iyi değil mi?**
> MD5 collision-resistant değil (kriptografik güvenlik için yetersiz) ama dosya bütünlüğü tespiti için yeterli.
> SHA-256 daha güvenli ama akademik bir ağ projesi için MD5 standart seçimdir.
> Üretim ortamında SHA-256 veya SHA-3 tercih edilir.

**S: Çoklu istemci desteği var mı?**
> Şu an yok — server tek seferlik (`serve_once`) yapıda.
> Eklemek için: her istemciden gelen ilk paketi farklı porta yönlendir veya
> `addr` bazlı bir dict tut, her istemci için ayrı `received` buffer.
> Bonus feature listesinde var, implement etmedik ama mimarisi açıklanabilir.

**S: Wireshark'ta bu paketleri görebilir misiniz?**
> Evet! UDP portuna filtre koy: `udp.port == 9999`
> Binary paketlerin hex dump'ını görebilirsin.
> Header'daki byte'ları elle decode edebilirsin (type, seq, total, len, crc, payload).
> Bu projenin bonus özelliği olarak Wireshark analizi yapılabilir.

---

## BÖLÜM 3 – Demo Senaryosu (Canlı)

```bash
# 1. Test dosyası oluştur (zaten var ama göster)
python generate_test_files.py

# 2. Normal transfer (0% loss)
python server.py --port 9999 &
python client.py test_data/file_256k.bin --port 9999

# 3. Kayıplı transfer (10% loss)
python server.py --port 9999 --loss 0.10 &
python client.py test_data/file_256k.bin --port 9999 --loss 0.10

# 4. Sliding window demo
python server.py --port 9999 &
python client.py test_data/file_512k.bin --port 9999 --window 8

# 5. Tüm deneyleri otomatik çalıştır
python experiments.py
```

---

## BÖLÜM 4 – Slayt Konuşma Metni (Kopyala-Yapıştır)

**Açılış:**
"Merhaba, sunumum NetProbe projesi üzerine. Bu projede UDP soketi üzerinde
güvenilir dosya aktarımı, trafik izleme ve performans analizi yapan bir platform geliştirdik."

**Mimari:**
"Sistem bir istemci-sunucu mimarisine dayanıyor. İstemci dosyayı parçalara bölerek
sıra numaralı UDP paketleriyle gönderiyor. Sunucu her paketi aldığında ACK gönderiyor.
ACK gelmezse istemci timeout yaşıyor ve yeniden gönderiyor. Aktarım sonunda MD5 hash ile
bütünlük doğrulanıyor."

**Protokol:**
"Kendi uygulama katmanı protokolümüzü tasarladık. Veri paketleri: tip, sıra numarası,
toplam paket sayısı, payload uzunluğu, CRC-32 checksum ve asıl veriyi içeriyor.
Tüm alanlar big-endian binary formatında struct ile serileştirildi."

**Demo:**
"Şimdi canlı demo yapacağım. Soldaki terminalde sunucu çalışıyor, sağda istemci
256KB dosyayı gönderiyor. %10 kayıp simülasyonuyla — bakın, timeout mesajları görünüyor,
sistem otomatik yeniden gönderiyor, sonunda dosya bütünlüğü MD5 ile doğrulanıyor: OK."

**Sonuç:**
"Projede UDP üzerinde tam güvenilir aktarım mekanizması, kapsamlı loglama ve
otomatik deney altyapısı geliştirdik. Sliding window bonus özelliği de çalışıyor."

---

## BÖLÜM 5 – Tanımlar (Ezber)

| Terim | Tanım |
|-------|-------|
| **UDP** | Bağlantısız, güvenilir olmayan, düşük gecikmeli transport protokolü |
| **TCP** | Bağlantı odaklı, güvenilir, sıralı, akış kontrolü olan transport protokolü |
| **Sequence Number** | Her pakete atanan benzersiz sıra numarası; sıralama ve kayıp tespiti için |
| **ACK** | Acknowledgement – alınan paketin onaylandığını bildiren kontrol mesajı |
| **Timeout** | ACK bekleme süresi; geçince retransmission tetiklenir |
| **Retransmission** | Kayıp veya bozulan paketin tekrar gönderilmesi |
| **Throughput** | Kanala gönderilen toplam veri / süre (retransmission dahil) |
| **Goodput** | Hedefe başarıyla iletilen faydalı veri / süre |
| **RTT** | Round-Trip Time – paket gönderiminden ACK alımına kadar geçen süre |
| **CRC-32** | Cyclic Redundancy Check – paket bozulma tespiti için checksum |
| **MD5** | Message Digest 5 – dosya bütünlüğü için kriptografik hash |
| **Stop-and-Wait** | Her paketten sonra ACK bekleyen en basit ARQ protokolü |
| **Sliding Window** | W paket ACK beklemeden gönderilebilen, verimli ARQ protokolü |
| **Go-Back-N** | Kayıp paketten itibaren penceredeki tüm paketlerin yeniden gönderildiği SW protokolü |
| **Selective Repeat** | Sadece kayıp paketin yeniden gönderildiği, daha verimli SW protokolü |
| **ARQ** | Automatic Repeat reQuest – hata tespitinde otomatik yeniden gönderim mekanizması |
| **Duplicate Detection** | Aynı seq numaralı paketin ikinci kez alınmasının tespiti |
| **MTU** | Maximum Transmission Unit – ağda tek seferde taşınabilecek maksimum paket boyutu (Ethernet: 1500B) |
| **Fragmentation** | MTU'yu aşan paketin IP katmanında parçalanması |
| **Socket** | Ağ iletişimi için uygulama-OS arayüzü; (IP, port) çiftiyle tanımlanır |

---

## BÖLÜM 6 – Değerlendirme Rubriği Kontrol Listesi

| Kriter | Ağırlık | Durumun |
|--------|---------|---------|
| Temel sistem çalışıyor | %20 | ✓ UDP client+server, dosya aktarımı çalışıyor |
| Güvenilir aktarım | %20 | ✓ Seq number, ACK, timeout, retransmit, duplicate detection |
| Trafik izleme & loglama | %15 | ✓ CSV log, tüm eventler kaydediliyor |
| Performans analizi | %20 | ✓ Throughput, goodput, RTT, retrans_rate, grafik |
| Kod kalitesi | %10 | ✓ Modüler yapı (5 ayrı dosya), yorum satırları |
| Rapor kalitesi | %10 | Hazırlanacak |
| Sunum & demo | %5 | ✓ Canlı demo hazır |

**Bonus puan için:** Sliding window ✓ | Loss simulator ✓ | Wireshark analizi (isteğe bağlı)

---

*Bu rehber projeden maksimum not almak için hazırlanmıştır. Her soruyu kendi cümlelerinle açıklayabilmek için birkaç kez oku.*
