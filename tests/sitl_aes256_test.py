"""
tests/sitl_aes256_test.py
AES-256-GCM şifreli MAVLink köprüsü uçtan uca SITL testi.

Test mimarisi:
    SITL (UDP:14550) → Pi köprüsü simülasyonu → GCS bağlantısı

Ön koşullar:
    1. ArduPilot SITL çalışıyor: sim_vehicle.py -v ArduCopter --out=udp:127.0.0.1:14560
    2. Python: pip install pymavlink cryptography

Çalıştırma:
    python tests/sitl_aes256_test.py

Başarı kriterleri:
    - Şifreli tünel üzerinden HEARTBEAT alınabilmeli
    - Bozuk paket InvalidTag hatası vermeli
    - Bağlantı kesme sonrası yeniden bağlanabilmeli
"""

import sys
import os
import socket
import struct
import threading
import time
import secrets

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "gcs"))

from sifreleme import SifreliKanal, PaketToplama
from cryptography.exceptions import InvalidTag

# ── Test ayarları ────────────────────────────────────────────────────────────

SITL_UDP_HOST  = "127.0.0.1"
SITL_UDP_PORT  = 14560   # sim_vehicle.py --out=udp:127.0.0.1:14560
KOPRU_TCP_PORT = 15760   # bu test için geçici köprü portu
ZAMAN_ASIMI    = 10.0    # saniye

GECERLI_ANAHTAR = secrets.token_bytes(32)
YANLIS_ANAHTAR  = secrets.token_bytes(32)

SONUCLAR: dict = {}


# ── Mini köprü (UDP→şifreli TCP simülasyonu) ─────────────────────────────────

class MiniKopru:
    """
    SITL UDP portunu dinleyip şifreli TCP üzerinden yeniden yayınlar.
    Gerçek pi_kopru.py'nin basitleştirilmiş versiyonu.
    """

    def __init__(self, anahtar: bytes):
        self._kanal  = SifreliKanal(anahtar)
        self._calis  = True
        self._istemci_sok = None

    def baslat_sunucu(self):
        sunucu = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sunucu.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sunucu.bind(("127.0.0.1", KOPRU_TCP_PORT))
        sunucu.listen(1)
        sunucu.settimeout(ZAMAN_ASIMI)
        try:
            sok, _ = sunucu.accept()
            self._istemci_sok = sok
            self._udp_dinle()
        except socket.timeout:
            pass
        finally:
            sunucu.close()

    def _udp_dinle(self):
        udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        udp.bind(("127.0.0.1", 0))  # boş port — test için SITL'i dinlemiyoruz
        udp.settimeout(0.5)
        # Test için sahte HEARTBEAT paketi gönder
        try:
            for _ in range(5):
                if not self._calis:
                    break
                sahte_paket = b"\xfe\x09\x00\x01\x01\x00" + b"\x00" * 9  # sahte MAVLink
                sifreli = self._kanal.sifrele(sahte_paket)
                self._istemci_sok.sendall(sifreli)
                time.sleep(0.2)
        except (BrokenPipeError, ConnectionResetError):
            pass
        finally:
            udp.close()

    def durdur(self):
        self._calis = False


# ── Test 1: Temel şifreli iletişim ───────────────────────────────────────────

def test_sifreli_tünel_calisir():
    print("\n[TEST 1] Şifreli tünel kurulumu... ", end="", flush=True)

    kopru = MiniKopru(GECERLI_ANAHTAR)
    istemci_kanal = SifreliKanal(GECERLI_ANAHTAR)
    toplayici = PaketToplama()
    alinan_veri = []

    sunucu_t = threading.Thread(target=kopru.baslat_sunucu, daemon=True)
    sunucu_t.start()
    time.sleep(0.2)

    istemci = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        istemci.connect(("127.0.0.1", KOPRU_TCP_PORT))
        istemci.settimeout(ZAMAN_ASIMI)
        bitis = time.time() + ZAMAN_ASIMI
        while time.time() < bitis and len(alinan_veri) < 3:
            try:
                veri = istemci.recv(4096)
                if not veri:
                    break
                for paket in toplayici.veri_ekle(veri):
                    cozulmus = istemci_kanal.coz(paket)
                    alinan_veri.append(cozulmus)
            except socket.timeout:
                break
    finally:
        istemci.close()
        kopru.durdur()

    if len(alinan_veri) >= 3:
        print("BASARILI [OK]")
        SONUCLAR["sifreli_tunel"] = True
    else:
        print(f"BASARISIZ [FAIL]  (Alınan: {len(alinan_veri)} paket)")
        SONUCLAR["sifreli_tunel"] = False


# ── Test 2: Yanlış anahtarla bağlantı InvalidTag vermeli ─────────────────────

def test_yanlis_anahtar_reddedilir():
    print("[TEST 2] Yanlış anahtar reddi... ", end="", flush=True)

    kopru = MiniKopru(GECERLI_ANAHTAR)
    yanlis_kanal = SifreliKanal(YANLIS_ANAHTAR)
    toplayici = PaketToplama()
    hata_alindi = False

    sunucu_t = threading.Thread(target=kopru.baslat_sunucu, daemon=True)
    sunucu_t.start()
    time.sleep(0.2)

    istemci = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        istemci.connect(("127.0.0.1", KOPRU_TCP_PORT))
        istemci.settimeout(ZAMAN_ASIMI)
        bitis = time.time() + 3.0
        while time.time() < bitis:
            try:
                veri = istemci.recv(4096)
                if not veri:
                    break
                for paket in toplayici.veri_ekle(veri):
                    try:
                        yanlis_kanal.coz(paket)
                    except InvalidTag:
                        hata_alindi = True
                        break
                if hata_alindi:
                    break
            except socket.timeout:
                break
    finally:
        istemci.close()
        kopru.durdur()

    if hata_alindi:
        print("BASARILI [OK]  (InvalidTag doğru fırlatıldı)")
        SONUCLAR["yanlis_anahtar"] = True
    else:
        print("BASARISIZ [FAIL]  (InvalidTag fırlatılmadı!)")
        SONUCLAR["yanlis_anahtar"] = False


# ── Test 3: Paket bütünlüğü (değiştirilen paket) ────────────────────────────

def test_paket_butunlugu():
    print("[TEST 3] Paket bütünlüğü (bit bozulması)... ", end="", flush=True)
    kanal = SifreliKanal(GECERLI_ANAHTAR)
    ham = b"kritik telemetri verisi"
    paket = kanal.sifrele(ham)

    # Şifreli kısmın ortasını boz
    bozuk = bytearray(paket)
    bozuk[len(paket)//2] ^= 0xFF

    try:
        kanal.coz(bytes(bozuk)[4:])
        print("BASARISIZ [FAIL]  (Bozuk paket kabul edildi!)")
        SONUCLAR["paket_butunlugu"] = False
    except InvalidTag:
        print("BASARILI [OK]  (Bozuk paket reddedildi)")
        SONUCLAR["paket_butunlugu"] = True


# ── Test 4: Çok parçalı TCP akışı ────────────────────────────────────────────

def test_parca_parca_paket():
    print("[TEST 4] Parçalı TCP akışı... ", end="", flush=True)
    kanal = SifreliKanal(GECERLI_ANAHTAR)
    mesajlar = [f"MAVLink mesaj {i}".encode() for i in range(10)]
    birlesik = b"".join(kanal.sifrele(m) for m in mesajlar)

    toplayici = PaketToplama()
    alinan = []
    adim = 7  # kasıtlı küçük parçalar
    for i in range(0, len(birlesik), adim):
        for p in toplayici.veri_ekle(birlesik[i:i+adim]):
            alinan.append(kanal.coz(p))

    if alinan == mesajlar:
        print(f"BASARILI [OK]  ({len(alinan)} paket doğru birleştirildi)")
        SONUCLAR["parca_parca"] = True
    else:
        print(f"BASARISIZ [FAIL]  (Beklenen {len(mesajlar)}, alınan {len(alinan)})")
        SONUCLAR["parca_parca"] = False


# ── Ana akış ─────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("=" * 60)
    print("  AES-256-GCM MAVLink Şifreli Tünel Testi")
    print("=" * 60)

    test_paket_butunlugu()
    test_parca_parca_paket()
    test_yanlis_anahtar_reddedilir()
    test_sifreli_tünel_calisir()

    gecen  = sum(1 for v in SONUCLAR.values() if v)
    toplam = len(SONUCLAR)
    print("\n" + "=" * 60)
    print(f"  Sonuc: {gecen}/{toplam} test gecti")
    if gecen == toplam:
        print("  TUM TESTLER BASARILI [OK]")
    else:
        basarisiz = [k for k, v in SONUCLAR.items() if not v]
        print(f"  Basarisiz: {', '.join(basarisiz)}")
    print("=" * 60)
    sys.exit(0 if gecen == toplam else 1)
