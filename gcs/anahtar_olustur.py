"""
anahtar_olustur.py
AES-256 anahtarı oluşturur ve dosyaya kaydeder.

Kullanım:
    python anahtar_olustur.py

Sonra Pi'ye kopyala:
    scp gcs_anahtar.key pi@<PI_IP>:~/dogus-gcs/
"""

import secrets
import os
import sys

ANAHTAR_DOSYA = "gcs_anahtar.key"


def anahtar_olustur():
    if os.path.exists(ANAHTAR_DOSYA):
        print(f"UYARI: '{ANAHTAR_DOSYA}' zaten mevcut.")
        cevap = input("Üzerine yaz? (e/h): ").strip().lower()
        if cevap != "e":
            print("İptal edildi.")
            return

    anahtar = secrets.token_bytes(32)  # 256 bit

    with open(ANAHTAR_DOSYA, "wb") as f:
        f.write(anahtar)

    os.chmod(ANAHTAR_DOSYA, 0o600)  # sadece sahibi okusun

    print(f"✓ AES-256 anahtar oluşturuldu: {ANAHTAR_DOSYA}")
    print(f"  Boyut : {len(anahtar) * 8} bit")
    print(f"  Hex   : {anahtar.hex()[:32]}…")
    print()
    print("Pi'ye kopyalamak için:")
    print(f"  scp {ANAHTAR_DOSYA} pi@<PI_IP>:~/dogus-gcs/")
    print()
    print("UYARI: Bu dosyayı git'e commit etme!")


if __name__ == "__main__":
    anahtar_olustur()
