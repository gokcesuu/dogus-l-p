"""
tests/test_sifreleme.py
AES-256-GCM şifreleme modülü birim testleri.

Çalıştırmak için (repo kökünden):
    pytest tests/test_sifreleme.py -v
"""

import os
import struct
import pytest

# gcs/ klasöründen import edebilmek için path ekle
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "gcs"))

from sifreleme import SifreliKanal, PaketToplama
from cryptography.exceptions import InvalidTag


ANAHTAR_32 = os.urandom(32)
ANAHTAR_FARKLI = os.urandom(32)


class TestSifreliKanal:

    def test_sifre_coz_geri_donusu(self):
        kanal = SifreliKanal(ANAHTAR_32)
        ham = b"MAVLink telemetri paketi 1234"
        paket = kanal.sifrele(ham)
        # başlık (4B) + nonce (12B) + şifreli + tag (16B)
        uzunluk = struct.unpack(">I", paket[:4])[0]
        assert uzunluk == len(paket) - 4
        geri = kanal.coz(paket[4:])
        assert geri == ham

    def test_farkli_anahtar_invalid_tag(self):
        kanal1 = SifreliKanal(ANAHTAR_32)
        kanal2 = SifreliKanal(ANAHTAR_FARKLI)
        paket = kanal1.sifrele(b"gizli veri")
        with pytest.raises(InvalidTag):
            kanal2.coz(paket[4:])

    def test_bozulmus_paket_invalid_tag(self):
        kanal = SifreliKanal(ANAHTAR_32)
        paket = kanal.sifrele(b"test verisi")
        # ortadaki bir byte'ı boz
        bozuk = bytearray(paket[4:])
        bozuk[20] ^= 0xFF
        with pytest.raises(InvalidTag):
            kanal.coz(bytes(bozuk))

    def test_bos_veri_sifreleme(self):
        kanal = SifreliKanal(ANAHTAR_32)
        paket = kanal.sifrele(b"")
        geri = kanal.coz(paket[4:])
        assert geri == b""

    def test_buyuk_veri(self):
        kanal = SifreliKanal(ANAHTAR_32)
        ham = os.urandom(8192)
        paket = kanal.sifrele(ham)
        geri = kanal.coz(paket[4:])
        assert geri == ham

    def test_nonce_her_seferinde_farkli(self):
        kanal = SifreliKanal(ANAHTAR_32)
        ham = b"ayni mesaj"
        p1 = kanal.sifrele(ham)
        p2 = kanal.sifrele(ham)
        # nonce: paket[4:16]
        assert p1[4:16] != p2[4:16]

    def test_yanlis_anahtar_boyutu(self):
        with pytest.raises(ValueError):
            SifreliKanal(b"kisa_anahtar_16b")

    def test_cok_kisa_paket_value_error(self):
        kanal = SifreliKanal(ANAHTAR_32)
        with pytest.raises(ValueError):
            kanal.coz(b"\x00" * 5)


class TestPaketToplama:

    def test_tam_paket_tek_parca(self):
        kanal = SifreliKanal(ANAHTAR_32)
        ham = b"test paketi"
        paket = kanal.sifrele(ham)
        toplayici = PaketToplama()
        sonuc = toplayici.veri_ekle(paket)
        assert len(sonuc) == 1
        assert kanal.coz(sonuc[0]) == ham

    def test_iki_paket_ard_arda(self):
        kanal = SifreliKanal(ANAHTAR_32)
        p1 = kanal.sifrele(b"birinci")
        p2 = kanal.sifrele(b"ikinci")
        toplayici = PaketToplama()
        sonuc = toplayici.veri_ekle(p1 + p2)
        assert len(sonuc) == 2
        assert kanal.coz(sonuc[0]) == b"birinci"
        assert kanal.coz(sonuc[1]) == b"ikinci"

    def test_parcali_gelme(self):
        kanal = SifreliKanal(ANAHTAR_32)
        ham = b"bolunmus paket verisi"
        paket = kanal.sifrele(ham)
        toplayici = PaketToplama()
        # Paketi 3'e böl
        bolum = len(paket) // 3
        sonuc = toplayici.veri_ekle(paket[:bolum])
        assert sonuc == []
        sonuc = toplayici.veri_ekle(paket[bolum:2*bolum])
        assert sonuc == []
        sonuc = toplayici.veri_ekle(paket[2*bolum:])
        assert len(sonuc) == 1
        assert kanal.coz(sonuc[0]) == ham

    def test_bos_veri_ekleme(self):
        toplayici = PaketToplama()
        sonuc = toplayici.veri_ekle(b"")
        assert sonuc == []
