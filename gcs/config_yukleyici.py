"""
config_yukleyici.py
config.json'u yükler ve iç içe dict'e noktalı erişim sağlar.
"""

import json
import os

_CONFIG_YOLU = os.path.join(os.path.dirname(__file__), "..", "config.json")

_veri: dict = {}


def yukle(yol: str = _CONFIG_YOLU) -> dict:
    global _veri
    with open(os.path.expanduser(yol), encoding="utf-8") as f:
        _veri = json.load(f)
    return _veri


def al(anahtar_yolu: str, varsayilan=None):
    """
    Noktalı yol ile değer okur: al("batarya.dusuk_yuzde") → 25
    """
    if not _veri:
        yukle()
    parca = anahtar_yolu.split(".")
    dugum = _veri
    for p in parca:
        if not isinstance(dugum, dict) or p not in dugum:
            return varsayilan
        dugum = dugum[p]
    return dugum


# İlk import'ta otomatik yükle
try:
    yukle()
except FileNotFoundError:
    pass
