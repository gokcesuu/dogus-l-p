KOYU_TEMA = """
QMainWindow, QWidget { background-color: #0d1b2a; color: #c8d8e8; }
QTabWidget::pane { border: 1px solid #2a4060; }
QTabBar::tab {
    background: #0a1520; color: #7eb8e0; padding: 8px 20px;
    border: 1px solid #2a4060; border-bottom: none;
}
QTabBar::tab:selected { background: #1a3050; color: #ffffff; }
QGroupBox {
    border: 1px solid #2a4060; border-radius: 6px;
    margin-top: 8px; font-weight: bold; color: #7eb8e0;
}
QGroupBox::title { subcontrol-origin: margin; left: 8px; padding: 0 4px; }
QPushButton {
    background-color: #1a3050; color: #c8d8e8;
    border: 1px solid #2a4060; border-radius: 4px;
    padding: 6px 12px; font-size: 11px;
}
QPushButton:hover { background-color: #2a4a70; }
QPushButton:pressed { background-color: #0a2040; }
QPushButton:disabled { background-color: #0a1520; color: #445566; }
QLineEdit, QTextEdit {
    background-color: #0a1520; color: #c8d8e8;
    border: 1px solid #2a4060; border-radius: 4px; padding: 4px;
}
QTableWidget {
    background-color: #0a1520; color: #c8d8e8;
    border: 1px solid #2a4060; gridline-color: #1a3050;
}
QTableWidget::item:selected { background-color: #1a4060; }
QHeaderView::section {
    background-color: #0d2040; color: #7eb8e0;
    border: 1px solid #2a4060; padding: 4px; font-weight: bold;
}
QProgressBar {
    background-color: #0a1520; border: 1px solid #2a4060;
    border-radius: 4px; text-align: center; color: #c8d8e8;
}
QProgressBar::chunk { background-color: #1a6faf; border-radius: 3px; }
QLabel { color: #c8d8e8; }
QStatusBar { background-color: #0a1520; color: #7eb8e0; }
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
