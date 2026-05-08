"""
pi_kopru.py  —  Raspberry Pi üzerinde çalışır
Doğuş Üniversitesi LÖP – AES-256-GCM MAVLink Köprüsü

Mimari:
    GCS (şifreli TCP) ←→ [bu script] ←→ ArduPilot (düz seri port)

Kurulum (Pi terminali):
    pip install cryptography pyserial
    python pi_kopru.py

Varsayılan ayarlar:
    GCS bağlantısı : TCP 0.0.0.0:5760  (GCS bu porta bağlanır)
    ArduPilot seri : /dev/ttyAMA0, 115200 baud
    Anahtar dosyası: ~/dogus-gcs/gcs_anahtar.key
"""

import socket
import serial
import threading
import struct
import os
import sys
import time
import logging

sys.path.insert(0, os.path.dirname(__file__))
from sifreleme import SifreliKanal, PaketToplama, anahtari_yukle
from cryptography.exceptions import InvalidTag

# ── Ayarlar (config.json'dan okunur, yoksa varsayılan) ───────────────────────

try:
    import json as _json
    _cfg_yolu = os.path.join(os.path.dirname(__file__), "config.json")
    with open(_cfg_yolu, encoding="utf-8") as _f:
        _cfg = _json.load(_f).get("pi_kopru", {})
    DINLE_HOST    = _cfg.get("dinle_host",   "0.0.0.0")
    DINLE_PORT    = int(_cfg.get("dinle_port",    5760))
    SERI_PORT     = _cfg.get("seri_port",    "/dev/ttyAMA0")
    SERI_BAUD     = int(_cfg.get("seri_baud",    115200))
    ANAHTAR_DOSYA = os.path.expanduser(_cfg.get("anahtar_dosya", "~/dogus-gcs/gcs_anahtar.key"))
    TAMPON_BOYUT  = int(_cfg.get("tampon_boyut", 4096))
except Exception:
    DINLE_HOST    = "0.0.0.0"
    DINLE_PORT    = 5760
    SERI_PORT     = "/dev/ttyAMA0"
    SERI_BAUD     = 115200
    ANAHTAR_DOSYA = os.path.expanduser("~/dogus-gcs/gcs_anahtar.key")
    TAMPON_BOYUT  = 4096

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("pi_kopru")


# ── Köprü sınıfı ──────────────────────────────────────────────────────────────

class MAVLinkKoprusu:
    def __init__(self, anahtar: bytes):
        self._kanal   = SifreliKanal(anahtar)
        self._seri    = None
        self._gcs_sok = None
        self._calis   = True

    def baslat(self):
        # Seri portu aç
        try:
            self._seri = serial.Serial(SERI_PORT, SERI_BAUD, timeout=0.1)
            log.info(f"Seri port açıldı: {SERI_PORT} @ {SERI_BAUD}")
        except Exception as e:
            log.error(f"Seri port açılamadı: {e}")
            sys.exit(1)

        # TCP sunucu
        sunucu = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sunucu.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sunucu.bind((DINLE_HOST, DINLE_PORT))
        sunucu.listen(1)
        log.info(f"GCS bağlantısı bekleniyor: {DINLE_HOST}:{DINLE_PORT}")

        while self._calis:
            try:
                gcs_sok, adres = sunucu.accept()
                log.info(f"GCS bağlandı: {adres}")
                self._gcs_sok = gcs_sok
                self._kopruyu_calistir(gcs_sok)
                log.info("GCS bağlantısı kesildi, yeniden bekleniyor…")
            except Exception as e:
                log.error(f"Sunucu hatası: {e}")
                time.sleep(2)

    def _kopruyu_calistir(self, gcs_sok: socket.socket):
        # İki yönlü veri aktarımı
        gcs_gelen = threading.Thread(
            target=self._gcs_den_ardupilota, args=(gcs_sok,), daemon=True
        )
        ardupilot_gelen = threading.Thread(
            target=self._ardupilottan_gcse, args=(gcs_sok,), daemon=True
        )
        gcs_gelen.start()
        ardupilot_gelen.start()
        gcs_gelen.join()   # GCS kapanınca dur
        ardupilot_gelen.join(timeout=1)

    def _gcs_den_ardupilota(self, gcs_sok: socket.socket):
        """GCS → Pi (şifreli) → ArduPilot (düz)"""
        toplayici = PaketToplama()
        try:
            while True:
                veri = gcs_sok.recv(TAMPON_BOYUT)
                if not veri:
                    break
                for paket in toplayici.veri_ekle(veri):
                    try:
                        acik = self._kanal.coz(paket)
                        self._seri.write(acik)
                    except InvalidTag:
                        log.warning("GCS→ArduPilot: Geçersiz auth tag! Paket atlandı.")
                    except Exception as e:
                        log.error(f"Çözme hatası: {e}")
        except Exception as e:
            log.info(f"GCS bağlantısı kapandı: {e}")

    def _ardupilottan_gcse(self, gcs_sok: socket.socket):
        """ArduPilot (düz) → Pi (şifreli) → GCS"""
        try:
            while True:
                veri = self._seri.read(TAMPON_BOYUT)
                if not veri:
                    time.sleep(0.001)
                    continue
                try:
                    sifreli = self._kanal.sifrele(veri)
                    gcs_sok.sendall(sifreli)
                except Exception as e:
                    log.error(f"Şifreleme/gönderme hatası: {e}")
                    break
        except Exception as e:
            log.info(f"ArduPilot okuma kapandı: {e}")


# ── Giriş noktası ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    log.info("Doğuş ÜNİ LÖP – MAVLink AES-256-GCM Köprüsü")
    log.info("=" * 50)

    try:
        anahtar = anahtari_yukle(ANAHTAR_DOSYA)
        log.info(f"Anahtar yüklendi: {ANAHTAR_DOSYA}")
    except FileNotFoundError as e:
        log.error(str(e))
        sys.exit(1)

    kopru = MAVLinkKoprusu(anahtar)
    try:
        kopru.baslat()
    except KeyboardInterrupt:
        log.info("Durduruldu.")
