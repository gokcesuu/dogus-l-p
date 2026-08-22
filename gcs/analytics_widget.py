"""
Analytics Panel Widget — Real-time metrikleri PyQt5 tablosunda göstrir.

GCS'nin "Analytics" sekmesine yerleştirilir, canlı ve replay modunda çalışır.
"""

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTableWidget, QTableWidgetItem,
    QLabel, QPushButton, QHeaderView, QScrollArea, QTabWidget,
)
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QFont, QColor, QBrush

from analytics import AnalyticsMetrics


class AnalyticsPanel(QWidget):
    """Metrikleri tablo + grafik olarak gösteren panel."""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.metrics: AnalyticsMetrics = None
        self._init_ui()
    
    def _init_ui(self):
        """UI öğelerini oluştur."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(8)
        
        # Başlık
        title = QLabel("📊 Uçuş Analytics")
        title_font = QFont("Barlow Condensed", 12, QFont.Bold)
        title.setFont(title_font)
        title.setStyleSheet("color: #94bce3;")
        layout.addWidget(title)
        
        # Tab: Temel / Güvenlik / Gelişmiş
        self._tabs = QTabWidget()
        self._tabs.setStyleSheet("""
            QTabBar::tab { padding: 4px 12px; }
            QTabWidget::pane { border: none; }
        """)
        
        self._tab_basic = self._create_basic_table()
        self._tab_safety = self._create_safety_table()
        self._tab_advanced = self._create_advanced_table()
        
        self._tabs.addTab(self._tab_basic, "Temel Metrikler")
        self._tabs.addTab(self._tab_safety, "Güvenlik/Perf.")
        self._tabs.addTab(self._tab_advanced, "Gelişmiş")
        
        layout.addWidget(self._tabs)
        
        # Export butonu
        btn_layout = QHBoxLayout()
        self._btn_export = QPushButton("📋 Rapor İndir")
        self._btn_export.setToolTip("CSV/PDF analytics raporu indir")
        btn_layout.addStretch()
        btn_layout.addWidget(self._btn_export)
        layout.addLayout(btn_layout)
    
    def _create_basic_table(self) -> QTableWidget:
        """Temel metriklerin tablosunu oluştur."""
        table = QTableWidget()
        table.setColumnCount(2)
        table.setHorizontalHeaderLabels(["Metrik", "Değer"])
        table.horizontalHeader().setStretchLastSection(True)
        table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        table.setSelectionBehavior(table.SelectRows)
        table.setSelectionMode(table.NoSelection)
        table.setStyleSheet("""
            QTableWidget { gridline-color: rgba(148, 188, 227, 0.12); }
            QHeaderView::section { background-color: #1d2d3d; color: #94bce3; }
        """)
        
        rows_data = [
            ("Uçuş Süresi", "—"),
            ("Kat Edilen Mesafe", "—"),
            ("Maksimum İrtifa", "—"),
            ("Ortalama İrtifa", "—"),
            ("Maksimum Hız", "—"),
            ("Ortalama Hız", "—"),
            ("Enerji Tüketimi", "—"),
        ]
        
        table.setRowCount(len(rows_data))
        for i, (metric, value) in enumerate(rows_data):
            item_m = QTableWidgetItem(metric)
            item_v = QTableWidgetItem(value)
            item_v.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            table.setItem(i, 0, item_m)
            table.setItem(i, 1, item_v)
        
        table.resizeRowsToContents()
        return table
    
    def _create_safety_table(self) -> QTableWidget:
        """Güvenlik metriklerinin tablosunu oluştur."""
        table = QTableWidget()
        table.setColumnCount(2)
        table.setHorizontalHeaderLabels(["Metrik", "Değer"])
        table.horizontalHeader().setStretchLastSection(True)
        table.setStyleSheet("""
            QTableWidget { gridline-color: rgba(148, 188, 227, 0.12); }
            QHeaderView::section { background-color: #1d2d3d; color: #94bce3; }
        """)
        
        rows_data = [
            ("Eve Maksimum Uzaklık (Drift)", "—"),
            ("Min. Batarya Hücre Voltajı", "—"),
            ("EKF Hata Sayısı", "—"),
            ("EKF Hata Süresi", "—"),
            ("RC Kaybı Sayısı", "—"),
            ("RC Kaybı Süresi", "—"),
            ("GPS Kaybı Sayısı", "—"),
            ("GPS Kaybı Süresi", "—"),
            ("Maks. İniş Hızı", "—"),
            ("Ortalama Rüzgar Hızı", "—"),
            ("Maksimum Rüzgar Hızı", "—"),
        ]
        
        table.setRowCount(len(rows_data))
        for i, (metric, value) in enumerate(rows_data):
            item_m = QTableWidgetItem(metric)
            item_v = QTableWidgetItem(value)
            item_v.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            table.setItem(i, 0, item_m)
            table.setItem(i, 1, item_v)
        
        table.resizeRowsToContents()
        return table
    
    def _create_advanced_table(self) -> QTableWidget:
        """Gelişmiş metriklerin tablosunu oluştur."""
        table = QTableWidget()
        table.setColumnCount(2)
        table.setHorizontalHeaderLabels(["Metrik", "Değer"])
        table.horizontalHeader().setStretchLastSection(True)
        table.setStyleSheet("""
            QTableWidget { gridline-color: rgba(148, 188, 227, 0.12); }
            QHeaderView::section { background-color: #1d2d3d; color: #94bce3; }
        """)
        
        rows_data = [
            ("Min. IMU Sıcaklığı", "—"),
            ("Maks. IMU Sıcaklığı", "—"),
            ("Mod Değişim Sayısı", "—"),
            ("Maksimum Titreşim", "—"),
        ]
        
        table.setRowCount(len(rows_data))
        for i, (metric, value) in enumerate(rows_data):
            item_m = QTableWidgetItem(metric)
            item_v = QTableWidgetItem(value)
            item_v.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            table.setItem(i, 0, item_m)
            table.setItem(i, 1, item_v)
        
        table.resizeRowsToContents()
        return table
    
    def update_metrics(self, metrics: AnalyticsMetrics):
        """Metrikleri güncelle ve tabloları yenile."""
        self.metrics = metrics
        self._refresh_tables()
    
    def _refresh_tables(self):
        """Tüm tabloları güncellenmiş metriklerle doldur."""
        if not self.metrics:
            return
        
        m = self.metrics
        
        # TEMEL TAB
        basic_rows = [
            f"{m.flight_duration_s:.1f} sn",
            f"{m.distance_traveled_m:.1f} m",
            f"{m.max_altitude_m:.1f} m",
            f"{m.avg_altitude_m:.1f} m",
            f"{m.max_speed_ms:.2f} m/s",
            f"{m.avg_speed_ms:.2f} m/s",
            f"{m.energy_consumed_mah:.0f} mAh" + (
                f" ({m.energy_consumed_wh:.1f} Wh)" 
                if m.energy_consumed_wh is not None else ""
            ),
        ]
        for i, val in enumerate(basic_rows):
            self._tab_basic.item(i, 1).setText(val)
        
        # GÜVENLİK TAB
        safety_rows = [
            f"{m.max_distance_from_home_m:.1f} m",
            f"{m.min_battery_cell_volt:.2f} V",
            f"{m.ekf_error_count}",
            f"{m.ekf_error_duration_s:.1f} sn",
            f"{m.rc_signal_loss_count}",
            f"{m.rc_signal_loss_duration_s:.1f} sn",
            f"{m.gps_signal_loss_count}",
            f"{m.gps_signal_loss_duration_s:.1f} sn",
            f"{m.max_descent_rate_ms:.2f} m/s",
            f"{m.avg_wind_speed_ms:.2f} m/s",
            f"{m.max_wind_speed_ms:.2f} m/s",
        ]
        for i, val in enumerate(safety_rows):
            item = self._tab_safety.item(i, 1)
            item.setText(val)
            
            # Renk kodlama: kritik değerler kırmızı
            color = None
            if i == 1 and m.min_battery_cell_volt < 3.3:  # Kritik voltaj
                color = QColor("#d4473f")
            elif i == 2 and m.ekf_error_count > 0:  # EKF hataları var
                color = QColor("#f5a623")
            elif i == 4 and m.rc_signal_loss_count > 0:  # RC kaybı
                color = QColor("#f5a623")
            elif i == 6 and m.gps_signal_loss_count > 0:  # GPS kaybı
                color = QColor("#f5a623")
            
            if color:
                item.setForeground(QBrush(color))
        
        # GELİŞMİŞ TAB
        advanced_rows = [
            f"{m.imu_temp_min:.1f}°C",
            f"{m.imu_temp_max:.1f}°C",
            f"{m.mode_change_count}",
            f"{m.max_vibration:.2f}",
        ]
        for i, val in enumerate(advanced_rows):
            self._tab_advanced.item(i, 1).setText(val)
    
    def reset(self):
        """Tüm metrikleri sıfırla."""
        for table in [self._tab_basic, self._tab_safety, self._tab_advanced]:
            for row in range(table.rowCount()):
                item = table.item(row, 1)
                if item:
                    item.setText("—")
                    item.setForeground(QBrush(QColor("#7eb8e0")))
