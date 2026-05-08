"""
sifreleme.py
AES-256-GCM şifreleme/çözme modülü.

Paket formatı: [nonce 12B] + [şifreli veri] + [auth tag 16B]
- nonce  : her paket için rastgele, tekrar kullanılmaz
- GCM    : hem şifreler hem doğrular (değiştirilirse InvalidTag hatası)

Kurulum:
    pip install cryptography
"""

import os
import struct
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.exceptions import InvalidTag


NONCE_BOYUT = 12   # GCM için standart
TAG_BOYUT   = 16   # GCM auth tag


class SifreliKanal:
    """
    AES-256-GCM ile MAVLink byte akışını şifreler/çözer.
    Her iki taraf (GCS ve Pi) aynı anahtarla başlatılır.
    """

    def __init__(self, anahtar: bytes):
        if len(anahtar) != 32:
            raise ValueError(f"Anahtar 32 byte (256 bit) olmalı, {len(anahtar)} byte verildi.")
        self._gcm = AESGCM(anahtar)

    # ── Şifreleme ────────────────────────────────────────────────────────────

    def sifrele(self, veri: bytes) -> bytes:
        """
        Ham MAVLink baytlarını şifreler.
        Çıktı: [uzunluk 4B big-endian] + [nonce 12B] + [şifreli+tag]
        """
        nonce    = os.urandom(NONCE_BOYUT)
        sifreli  = self._gcm.encrypt(nonce, veri, None)
        paket    = nonce + sifreli
        return struct.pack(">I", len(paket)) + paket

    def coz(self, paket: bytes) -> bytes:
        """
        Şifreli paketi çözer. Başlık (4B uzunluk) olmadan veri kısmını al.
        Veri değiştirildiyse InvalidTag hatası fırlatır.
        """
        if len(paket) < NONCE_BOYUT + TAG_BOYUT:
            raise ValueError("Paket çok kısa.")
        nonce   = paket[:NONCE_BOYUT]
        sifreli = paket[NONCE_BOYUT:]
        return self._gcm.decrypt(nonce, sifreli, None)


class PaketToplama:
    """
    TCP akışından tam paketleri toplar.
    Şifreli kanal 4 byte uzunluk başlığı kullanır.
    """

    def __init__(self):
        self._tampon = b""

    def veri_ekle(self, veri: bytes) -> list[bytes]:
        """Yeni gelen baytları ekle, tam paketleri döndür."""
        self._tampon += veri
        paketler = []
        while len(self._tampon) >= 4:
            uzunluk = struct.unpack(">I", self._tampon[:4])[0]
            if len(self._tampon) < 4 + uzunluk:
                break
            paketler.append(self._tampon[4:4 + uzunluk])
            self._tampon = self._tampon[4 + uzunluk:]
        return paketler


def anahtari_yukle(dosya: str = "gcs_anahtar.key") -> bytes:
    """Anahtar dosyasını okur. Yoksa hata verir."""
    if not os.path.exists(dosya):
        raise FileNotFoundError(
            f"Anahtar dosyası bulunamadı: {dosya}\n"
            f"Oluşturmak için: python anahtar_olustur.py"
        )
    with open(dosya, "rb") as f:
        anahtar = f.read()
    if len(anahtar) != 32:
        raise ValueError(f"Geçersiz anahtar boyutu: {len(anahtar)} byte (32 olmalı)")
    return anahtar
