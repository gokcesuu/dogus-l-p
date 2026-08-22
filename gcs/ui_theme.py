KOYU_TEMA = """
QMainWindow, QWidget { background-color: #16222e; color: #bdd8f2; font-family: 'Barlow', sans-serif; }
QTabWidget::pane { border: 1px solid rgba(148,188,227,0.22); }
QTabBar::tab {
    background: #111c26; color: #7e9cb8; padding: 8px 20px;
    border: 1px solid rgba(148,188,227,0.22); border-bottom: none;
    font-family: 'Barlow Condensed', sans-serif; font-weight: 600;
}
QTabBar::tab:selected { background: #1d2d3d; color: #e7e7ea; }
QGroupBox {
    border: 1px solid rgba(148,188,227,0.22); border-radius: 2px;
    margin-top: 8px; font-weight: 600; color: #7e9cb8;
    font-family: 'Barlow Condensed', sans-serif;
}
QGroupBox::title { subcontrol-origin: margin; left: 8px; padding: 0 4px; }
QPushButton {
    background-color: #1d2d3d; color: #bdd8f2;
    border: 1px solid rgba(148,188,227,0.28); border-radius: 4px;
    padding: 6px 12px; font-size: 11px;
    font-family: 'Barlow Condensed', sans-serif; font-weight: 600;
}
QPushButton:hover { background-color: rgba(148,188,227,0.16); }
QPushButton:pressed { background-color: #111c26; }
QPushButton:disabled { background-color: #111c26; color: #445566; }
QLineEdit, QTextEdit {
    background-color: #111c26; color: #bdd8f2;
    border: 1px solid rgba(148,188,227,0.28); border-radius: 4px; padding: 4px;
}
QTableWidget {
    background-color: #111c26; color: #bdd8f2;
    border: 1px solid rgba(148,188,227,0.22); gridline-color: #1d2d3d;
}
QTableWidget::item:selected { background-color: rgba(148,188,227,0.18); }
QHeaderView::section {
    background-color: #1d2d3d; color: #7e9cb8;
    border: 1px solid rgba(148,188,227,0.22); padding: 4px; font-weight: 600;
    font-family: 'Barlow Condensed', sans-serif;
}
QProgressBar {
    background-color: #111c26; border: 1px solid rgba(148,188,227,0.28);
    border-radius: 4px; text-align: center; color: #bdd8f2;
}
QProgressBar::chunk { background-color: #94bce3; border-radius: 3px; }
QLabel { color: #bdd8f2; }
QStatusBar { background-color: #111c26; color: #7e9cb8; }
"""

ACİL_STILI = """
QPushButton {
    background-color: #7b1414; color: #ffffff;
    border: 1px solid #b22222; border-radius: 4px;
    padding: 8px 16px; font-weight: bold; font-size: 12px;
}
QPushButton:hover { background-color: #b22222; }
"""

BAĞLAN_STILI = """
QPushButton {
    background-color: #1a5c2a; color: #ffffff;
    border: 1px solid #2e8b57; border-radius: 4px;
    padding: 6px 16px; font-weight: bold;
}
QPushButton:hover { background-color: #2e8b57; }
"""

UYARI_STILI = "background-color: #7b1414; color: white; font-weight: bold; padding: 4px;"

# ── Kokpit paleti (Türkçe Yer İstasyonu tasarımından) ──────────────────────
# Uçuş ve Harita ekranlarının paylaştığı ortak görsel dil.
KOKPIT_ZEMIN  = "#16222e"   # ana koyu zemin
KOKPIT_PANEL  = "#1d2d3d"   # panel/kart zemini
KOKPIT_KENAR  = "rgba(148,188,227,0.22)"  # ince ayraç/kenarlık
KOKPIT_VURGU  = "#94bce3"   # birincil vurgu (mavi)
KOKPIT_VURGU2 = "#bdd8f2"   # açık vurgu / hover
KOKPIT_ACIL   = "#8f3b34"   # acil buton zemini
KOKPIT_ACIL2  = "#c25b52"   # acil buton kenar/hover
KOKPIT_BASARI = "#8fbf7a"   # bağlı/başarı göstergesi

ACİL_STİLİ_KOKPIT = f"""
QPushButton {{
    background-color: {KOKPIT_ACIL}; color: #f5f5f8;
    border: 1px solid {KOKPIT_ACIL2}; border-radius: 4px;
    padding: 8px 16px; font-weight: bold; font-size: 12px;
}}
QPushButton:hover {{ background-color: #a8443c; }}
"""

BAĞLAN_STİLİ_KOKPIT = f"""
QPushButton {{
    background-color: {KOKPIT_VURGU}; color: #12202c;
    border: none; border-radius: 4px;
    padding: 6px 16px; font-weight: bold;
}}
QPushButton:hover {{ background-color: {KOKPIT_VURGU2}; }}
"""
