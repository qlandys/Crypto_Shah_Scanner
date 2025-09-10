# -*- coding: utf-8 -*-
import sys
import os
import json
import pyperclip
import re
import subprocess
import traceback
import time
from pathlib import Path
from PyQt5.QtWidgets import *
from PyQt5.QtWidgets import QCompleter, QTabWidget, QInputDialog, QSizePolicy, QGraphicsOpacityEffect
from PyQt5.QtCore import Qt, QThread, pyqtSignal, QPoint, QPointF, QPropertyAnimation, QEvent, QSize, QSettings, QEasingCurve, QTimer
from PyQt5.QtGui import (QIcon, QFont, QPalette, QColor, QStandardItemModel,
                         QStandardItem, QKeySequence, QPainter, QPixmap,
                         QLinearGradient, QBrush, QPen, QPolygonF)
from database_sqlite import Database, Coin
from parser import TradingViewParser
import multiprocessing
from parser import parse_coin_in_process, parse_coins_batch_process
import io
from clicker_window import ClickerWindow
from datetime import datetime, timedelta
import concurrent.futures
import math

# --- безопасная обёртка stdout/stderr ---
def _safe_rewrap_streams():
    for name in ("stdout", "stderr"):
        stream = getattr(sys, name, None)
        if stream and hasattr(stream, "buffer"):
            try:
                setattr(sys, name, io.TextIOWrapper(stream.buffer, encoding="utf-8", errors="replace"))
            except Exception:
                pass

_safe_rewrap_streams()

# Глобальная обработка исключений
def excepthook(exc_type, exc_value, exc_tb):
    tb = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
    print("Произошла ошибка:", tb)
    msg = QMessageBox()
    msg.setIcon(QMessageBox.Critical)
    msg.setText("Произошла критическая ошибка")
    msg.setInformativeText(str(exc_value))
    msg.setWindowTitle("Ошибка")
    msg.setDetailedText(tb)
    msg.exec_()

sys.excepthook = excepthook

# Добавляем очистку потоков
import cleanup_threads
cleanup_threads.register_cleanup()

# Настройка окружения для Playwright
def setup_playwright():
    if getattr(sys, 'frozen', False):
        base_path = Path(sys._MEIPASS) if hasattr(sys, '_MEIPASS') else Path(sys.executable).parent
        playwright_dir = base_path / "playwright"
        os.environ["PLAYWRIGHT_DRIVER_PATH"] = str(playwright_dir / "driver")
        browsers_path = Path(sys.executable).parent / "ms-playwright"
        os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(browsers_path)

        if not browsers_path.exists():
            print("Установка браузеров Playwright...")
            try:
                creationflags = 0
                if os.name == "nt":
                    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)

                subprocess.run(
                    [sys.executable, "-m", "playwright", "install", "chromium"],
                    check=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    creationflags=creationflags
                )
            except subprocess.CalledProcessError as e:
                try:
                    err = e.stderr.decode(errors='ignore')
                except Exception:
                    err = str(e)
                print(f"Ошибка установки браузеров: {err}")
                return False
            except Exception as e:
                print(f"Неизвестная ошибка при установке браузеров: {str(e)}")
                return False
        return True
    return True


class CopyNotification(QLabel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAlignment(Qt.AlignCenter)
        self.setStyleSheet("""
            background-color: #4CAF50;
            color: white;
            border-radius: 4px;
            padding: 2px 6px;
            font-weight: bold;
            font-size: 10px;
        """)
        self.setFixedHeight(20)

        # ВАЖНО: анимируем opacity через эффект
        self._opacity_effect = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(self._opacity_effect)

        self.animation = QPropertyAnimation(self._opacity_effect, b"opacity")
        self.animation.setDuration(1000)
        self.animation.setEasingCurve(QEasingCurve.OutCubic)
        self.animation.setStartValue(0.0)
        self.animation.setKeyValueAt(0.3, 1.0)
        self.animation.setKeyValueAt(0.7, 1.0)
        self.animation.setEndValue(0.0)
        self.animation.finished.connect(self.hide)

    def show_notification(self, button):
        self.setText("✓ Скопировано")
        global_pos = button.mapToGlobal(QPoint(0, 0))
        parent_pos = self.parent().mapFromGlobal(global_pos)
        self.move(parent_pos.x() - 10, parent_pos.y() + button.height() + 5)
        self.show()
        self.raise_()
        self.animation.start()

    def show_notification_at_pos(self, pos):
        self.setText("✓ Скопировано")
        local_pos = self.parent().mapFromGlobal(pos)
        self.move(local_pos.x() - 15, local_pos.y() - 25)
        self.show()
        self.raise_()
        self.animation.start()


class ExchangeFilterWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.layout = QHBoxLayout(self)
        self.layout.setContentsMargins(0, 0, 0, 0)

        self.label = QLabel("Все биржи")
        self.label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.label.setStyleSheet("""
            QLabel {
                background-color: #3A3A3A;
                color: #DDDDDD;
                border: 1px solid #555555;
                border-radius: 4px;
                padding: 6px 12px;
                min-width: 200px;
                font-size: 12px;
            }
        """)
        self.label.setCursor(Qt.PointingHandCursor)
        self.label.mousePressEvent = self.show_dialog
        self.layout.addWidget(self.label)

        self.dialog = QDialog(self)
        self.dialog.setWindowTitle("Выберите биржи")
        self.dialog.setFixedSize(320, 400)
        self.dialog.setStyleSheet("""
            QDialog {
                background-color: #2D2D2D;
                border: 1px solid #444444;
                border-radius: 8px;
                color: #DDDDDD;
            }
            QLineEdit {
                background-color: #3A3A3A;
                color: #DDDDDD;
                border: 1px solid #555555;
                border-radius: 4px;
                padding: 8px 12px;
                font-size: 13px;
            }
            QListWidget {
                background-color: #3A3A3A;
                color: #DDDDDD;
                border: 1px solid #555555;
                border-radius: 4px;
                font-size: 13px;
            }
            QPushButton {
                background-color: #6A5AF9;
                color: white;
                border: none;
                padding: 8px 15px;
                border-radius: 4px;
                font-weight: normal;
                font-size: 12px;
            }
            QPushButton:hover {
                background-color: #5B4AE9;
            }
        """)
        self.dialog_layout = QVBoxLayout(self.dialog)
        self.dialog_layout.setContentsMargins(12, 12, 12, 12)
        self.dialog_layout.setSpacing(12)

        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Поиск бирж...")
        self.search_input.setStyleSheet("font-size: 13px;")
        self.dialog_layout.addWidget(self.search_input)

        self.list_widget = QListWidget()
        self.list_widget.setStyleSheet("""
            QListWidget {
                background-color: #3A3A3A;
                color: #DDDDDD;
                font-size: 13px;
            }
            QListWidget::item {
                padding: 8px 12px;
                border-bottom: 1px solid #444444;
            }
            QListWidget::item:selected {
                background-color: #4A4A4A;
            }
        """)
        # не инвертируем вручную чекбоксы — Qt сам всё сделает
        self.dialog_layout.addWidget(self.list_widget, 1)

        btn_layout = QHBoxLayout()
        self.select_all_btn = QPushButton("Выбрать все")
        self.select_all_btn.clicked.connect(self.select_all)
        self.deselect_all_btn = QPushButton("Снять все")
        self.deselect_all_btn.clicked.connect(self.deselect_all)
        btn_layout.addWidget(self.select_all_btn)
        btn_layout.addWidget(self.deselect_all_btn)
        self.dialog_layout.addLayout(btn_layout)

        button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        button_box.setStyleSheet("background-color: transparent;")
        button_box.accepted.connect(self.accept_selection)
        button_box.rejected.connect(self.dialog.reject)
        self.dialog_layout.addWidget(button_box)

        self.search_input.textChanged.connect(self.filter_items)
        self.selected_exchanges = set()
        self.all_exchanges = []

    def set_exchanges(self, exchanges):
        self.all_exchanges = sorted(exchanges)
        self.list_widget.clear()
        for exchange in self.all_exchanges:
            item = QListWidgetItem(exchange)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked)
            self.list_widget.addItem(item)
        self.selected_exchanges = set(self.all_exchanges)
        self.update_label()

    def filter_items(self, text):
        text_lower = text.strip().lower()
        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            item_text = item.text().lower()
            item.setHidden(text_lower not in item_text)

    def select_all(self):
        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            item.setCheckState(Qt.Checked)

    def deselect_all(self):
        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            item.setCheckState(Qt.Unchecked)

    def show_dialog(self, event=None):
        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            if item.text() in self.selected_exchanges:
                item.setCheckState(Qt.Checked)
            else:
                item.setCheckState(Qt.Unchecked)
        self.search_input.clear()
        self.filter_items("")
        self.dialog.exec_()

    def accept_selection(self):
        self.selected_exchanges.clear()
        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            if item.checkState() == Qt.Checked:
                self.selected_exchanges.add(item.text())
        self.update_label()
        self.dialog.accept()

    def update_label(self):
        if not self.selected_exchanges:
            self.label.setText("Все биржи")
        elif len(self.selected_exchanges) <= 10:
            self.label.setText(", ".join(sorted(self.selected_exchanges)))
        else:
            self.label.setText(f"{len(self.selected_exchanges)} бирж выбрано")

        self.label.setStyleSheet("""
            QLabel {
                background-color: #3A3A3A;
                color: #DDDDDD;
                border: 1px solid #555555;
                border-radius: 4px;
                padding: 6px 12px;
                min-width: 200px;
                font-size: 12px;
            }
        """)
        if self.selected_exchanges:
            self.label.setToolTip(", ".join(sorted(self.selected_exchanges)))

    def get_selected_items(self):
        return list(self.selected_exchanges)


class ParseThread(QThread):
    finished = pyqtSignal(dict)
    error = pyqtSignal(str)

    def __init__(self, coin_name, thread_id):
        super().__init__()
        self.coin_name = coin_name
        self.thread_id = thread_id
        self.parser = None

    def run(self):
        try:
            self.parser = TradingViewParser(headless=True, instance_id=self.thread_id)
            data_tuple = self.parser.parse_coin(self.coin_name)
            data = data_tuple[1] if isinstance(data_tuple, tuple) and len(data_tuple) == 2 else data_tuple
            self.finished.emit(data)
        except Exception as e:
            self.error.emit(str(e))
        finally:
            if self.parser:
                self.parser.close()


class BatchParseThread(QThread):
    progress = pyqtSignal(int, int, str, str)  # current, total, coin, time_remaining
    finished = pyqtSignal()
    error = pyqtSignal(str, str)

    def __init__(self, coin_names, db, thread_id, max_workers=5):
        super().__init__()
        self.coin_names = coin_names
        self.db = db
        self.thread_id = thread_id
        self._is_cancelled = False
        self.start_time = None
        self.max_workers = max_workers
        self._executor = None
        self._futures = []

    def cancel(self):
        self._is_cancelled = True
        try:
            if self._executor:
                self._executor.shutdown(cancel_futures=True)
        except Exception:
            pass

    def run(self):
        total = len(self.coin_names)
        self.start_time = time.time()

        chunk_size = max(1, len(self.coin_names) // self.max_workers)
        chunks = [self.coin_names[i:i + chunk_size] for i in range(0, len(self.coin_names), chunk_size)]

        ctx = multiprocessing.get_context('spawn')
        with concurrent.futures.ProcessPoolExecutor(max_workers=self.max_workers, mp_context=ctx) as executor:
            self._executor = executor
            self._futures = [executor.submit(parse_coins_batch_process, chunk, True) for chunk in chunks]

            processed = 0
            for future in concurrent.futures.as_completed(self._futures):
                if self._is_cancelled:
                    break
                chunk = None
                try:
                    chunk_results = future.result()
                    for coin_name, result in chunk_results.items():
                        processed += 1
                        elapsed = time.time() - self.start_time
                        time_per_coin = elapsed / max(processed, 1)
                        remaining_seconds = max(0, time_per_coin * (total - processed))
                        hours = int(remaining_seconds // 3600)
                        minutes = int((remaining_seconds % 3600) // 60)
                        seconds = int(remaining_seconds % 60)
                        remaining_time = f"{hours:02d}:{minutes:02d}:{seconds:02d}"

                        if "error" in result:
                            self.error.emit(result["error"], coin_name)
                        else:
                            spot_str = ", ".join(result['spot']) if result['spot'] else ""
                            futures_str = ", ".join(result['futures']) if result['futures'] else ""
                            self.db.save_coin(result['name'], spot_str, futures_str)

                        self.progress.emit(processed, total, coin_name, remaining_time)
                except Exception as e:
                    # Если батч упал — считаем, что все его монеты с ошибкой
                    if chunk is None:
                        # без точного chunk — просто продвинем счётчик
                        processed += 1
                        self.progress.emit(processed, total, "?", "Ошибка батча")
                    self.error.emit(str(e), "batch")

        self.finished.emit()


class ProfileTab(QWidget):
    def __init__(self, profile_name, parent=None):
        super().__init__(parent)
        self.profile_name = profile_name
        self.db = None
        self.copy_notification = CopyNotification(self)
        self.copy_notification.hide()
        self.filtered_results = []

        try:
            self.db = Database(profile_name)
        except Exception as e:
            QMessageBox.warning(self, "Ошибка", f"Не удалось загрузить базу данных: {str(e)}")
            self.db = Database(profile_name)
            self.db.save()

        self.init_ui()
        self.apply_theme()
        self._build_star_icons_from_outline()  # подготовим иконки звезды (контур + заливка)
        self._load_metascalp_icons()
        self.update_exchange_list()
        self.reset_filters()

    def closeEvent(self, event):
        if hasattr(self, 'scan_thread') and getattr(self.scan_thread, 'isRunning', lambda: False)():
            try:
                self.scan_thread.terminate()
                self.scan_thread.wait(1000)
            except:
                pass

        if hasattr(self, 'batch_thread') and getattr(self.batch_thread, 'isRunning', lambda: False)():
            try:
                self.batch_thread.cancel()
                self.batch_thread.terminate()
                self.batch_thread.wait(1000)
            except:
                pass

        cleanup_threads.cleanup_threads()
        event.accept()

    def start_memory_cleanup(self):
        self.cleanup_timer = QTimer()
        self.cleanup_timer.timeout.connect(self.memory_cleanup)
        self.cleanup_timer.start(30000)

    def stop_memory_cleanup(self):
        if hasattr(self, 'cleanup_timer'):
            self.cleanup_timer.stop()
            self.cleanup_timer.deleteLater()

    def memory_cleanup(self):
        if hasattr(self, 'batch_thread') and getattr(self.batch_thread, 'isRunning', lambda: False)():
            import gc
            gc.collect()
            if sys.platform.startswith("linux"):
                try:
                    import ctypes
                    ctypes.CDLL('libc.so.6').malloc_trim(0)
                except:
                    pass

    def apply_theme(self):
        self.setStyleSheet("""
            QWidget {
                background-color: #1E1E1E;
                color: #DDDDDD;
            }
            QGroupBox {
                border: 1px solid #444444;
                border-radius: 8px;
                margin-top: 1ex;
                padding: 15px;
                color: #DDDDDD;
                font-weight: bold;
                font-size: 14px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px;
                background-color: transparent;
                margin-top: 10px;
            }
            QPushButton {
                background-color: #6A5AF9;
                color: white;
                border: none;
                padding: 8px 16px;
                border-radius: 4px;
                font-size: 12px;
            }
            QPushButton:hover {
                background-color: #5B4AE9;
            }
            QPushButton:disabled {
                background-color: #444444;
                color: #888888;
            }
            QLineEdit, QComboBox, QListWidget {
                background-color: #3A3A3A;
                color: #DDDDDD;
                border: 1px solid #555555;
                border-radius: 4px;
                padding: 8px 12px;
                font-size: 13px;
            }
            QLabel {
                color: #DDDDDD;
                font-size: 12px;
            }
            QProgressBar {
                border: 1px solid #555555;
                border-radius: 4px;
                background: #3A3A3A;
                text-align: center;
                color: #DDDDDD;
                height: 20px;
            }
            QProgressBar::chunk {
                background-color: #6A5AF9;
                width: 10px;
            }
            QTableWidget {
                background-color: #3A3A3A;
                gridline-color: #444444;
                color: #DDDDDD;
                border: 1px solid #444444;
                border-radius: 6px;
                font-size: 12px;
            }
            QHeaderView::section {
                background-color: #4A4A4A;
                color: #DDDDDD;
                padding: 8px;
                border: none;
                font-weight: bold;
                font-size: 12px;
            }
            QTableWidget::item {
                padding: 8px;
                background-color: #3A3A3A;
            }
            QTableWidget::item:selected {
                background-color: #5A5A5A;
                color: #DDDDDD;
            }
            QCheckBox {
                color: #DDDDDD;
                font-size: 12px;
            }
            QCheckBox::indicator {
                width: 16px;
                height: 16px;
            }
            QScrollArea {
                background-color: #1E1E1E;
            }
        """)

    def init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(15, 15, 15, 15)
        main_layout.setSpacing(15)

        scan_group = QGroupBox("Сканирование монеты")
        scan_layout = QVBoxLayout(scan_group)
        scan_layout.setSpacing(15)

        input_layout = QHBoxLayout()
        input_layout.setSpacing(10)

        self.coin_input = QLineEdit()
        self.coin_input.setPlaceholderText("Введите название монеты (например BTC)")
        self.coin_input.setMinimumHeight(36)
        self.scan_btn = QPushButton("Сканировать (Enter)")
        self.scan_btn.setMinimumHeight(36)
        self.scan_btn.clicked.connect(self.start_scan)
        self.load_file_btn = QPushButton("Загрузить файл")
        self.load_file_btn.setMinimumHeight(36)
        self.load_file_btn.clicked.connect(self.load_file)
        self.coin_input.returnPressed.connect(self.start_scan)

        input_layout.addWidget(self.coin_input, 5)
        input_layout.addWidget(self.scan_btn, 2)
        input_layout.addWidget(self.load_file_btn, 2)
        scan_layout.addLayout(input_layout)

        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        self.progress_bar.setRange(0, 0)
        self.progress_bar.setFormat("Сканирование...")
        scan_layout.addWidget(self.progress_bar)

        self.batch_progress_bar = QProgressBar()
        self.batch_progress_bar.setVisible(False)
        self.batch_progress_bar.setRange(0, 100)
        self.batch_progress_bar.setFormat("Ожидание начала сканирования")
        scan_layout.addWidget(self.batch_progress_bar)

        self.cancel_btn = QPushButton("Отменить")
        self.cancel_btn.setVisible(False)
        self.cancel_btn.clicked.connect(self.cancel_batch_scan)
        scan_layout.addWidget(self.cancel_btn)

        results_layout = QVBoxLayout()
        results_layout.setSpacing(8)

        name_layout = QHBoxLayout()
        name_layout.setContentsMargins(0, 0, 0, 0)
        name_layout.setSpacing(6)

        self.coin_name_label = QLabel("Название:")
        self.coin_name_label.setFont(QFont("Arial", 11, QFont.Bold))
        self.coin_name_value = QLabel("")
        self.coin_name_value.setFont(QFont("Arial", 11, QFont.Bold))
        self.coin_name_value.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Preferred)

        # ⭐ одиночное сканирование — звезда
        self.single_star_btn = QPushButton()
        self.single_star_btn.setCheckable(True)
        self.single_star_btn.setVisible(False)
        self.single_star_btn.setFixedSize(24, 24)
        self.single_star_btn.setStyleSheet("""
            QPushButton { background-color: transparent; border: none; padding: 0px; margin: 0px; }
        """)
        self.single_star_btn.clicked.connect(self.toggle_favorite_single)

        # Копировать тикер
        self.copy_btn = QPushButton()
        self.copy_btn.setFixedSize(28, 28)
        self.copy_btn.setStyleSheet("""
            QPushButton {
                background-color: #6A5AF9;
                border: none;
                border-radius: 14px;
            }
            QPushButton:hover {
                background-color: #5B4AE9;
            }
        """)
        if os.path.exists("icons/icon_copy.png"):
            self.copy_btn.setIcon(QIcon("icons/icon_copy.png"))
            self.copy_btn.setIconSize(QSize(16, 16))
        else:
            self.copy_btn.setText("C")
        self.copy_btn.setToolTip("Копировать название")
        self.copy_btn.clicked.connect(lambda: self.copy_coin_name(self.copy_btn))
        self.copy_btn.setVisible(False)

        # MetaScalp allow/deny — ПЛОСКИЕ иконки без фона
        self.metascalp_btn = QPushButton()
        self.metascalp_btn.setCheckable(True)
        self.metascalp_btn.setVisible(False)
        self.metascalp_btn.setFixedSize(24, 24)
        self.metascalp_btn.clicked.connect(self._toggle_metascalp)
        self._load_metascalp_icons()
        self._apply_metascalp_icon(self.metascalp_btn, True)

        # композиция
        name_layout.addWidget(self.coin_name_label)
        name_layout.addWidget(self.coin_name_value)
        name_layout.addSpacing(6)
        name_layout.addWidget(self.single_star_btn)   # ⭐ слева от копирования
        name_layout.addWidget(self.copy_btn)          # копировать
        name_layout.addWidget(self.metascalp_btn)     # справа — metascalp
        name_layout.addStretch()

        results_layout.addLayout(name_layout)

        spot_layout = QHBoxLayout()
        spot_label = QLabel("Спотовые биржи:")
        spot_label.setFont(QFont("Arial", 10))
        self.spot_value = QLabel("")
        self.spot_value.setFont(QFont("Arial", 10))
        self.spot_value.setWordWrap(True)
        spot_layout.addWidget(spot_label)
        spot_layout.addWidget(self.spot_value, 1)
        results_layout.addLayout(spot_layout)

        futures_layout = QHBoxLayout()
        futures_label = QLabel("Фьючерсные биржи:")
        futures_label.setFont(QFont("Arial", 10))
        self.futures_value = QLabel("")
        self.futures_value.setFont(QFont("Arial", 10))
        self.futures_value.setWordWrap(True)
        futures_layout.addWidget(futures_label)
        futures_layout.addWidget(self.futures_value, 1)
        results_layout.addLayout(futures_layout)
        scan_layout.addLayout(results_layout)
        main_layout.addWidget(scan_group)

        search_group = QGroupBox("Поиск по базе данных")
        search_layout = QVBoxLayout(search_group)
        search_layout.setSpacing(15)

        filter_layout = QGridLayout()
        filter_layout.setColumnStretch(1, 1)
        filter_layout.setColumnStretch(3, 1)
        filter_layout.setHorizontalSpacing(10)
        filter_layout.setVerticalSpacing(10)

        filter_layout.addWidget(QLabel("Поиск по названию:"), 0, 0)
        self.coin_search_input = QLineEdit()
        self.coin_search_input.setPlaceholderText("Введите название монеты")
        self.coin_search_input.setMinimumHeight(36)
        self.coin_search_input.returnPressed.connect(self.apply_filter)
        filter_layout.addWidget(self.coin_search_input, 0, 1, 1, 4)

        filter_layout.addWidget(QLabel("Выберите биржи:"), 1, 0)
        self.exchange_filter = ExchangeFilterWidget()
        filter_layout.addWidget(self.exchange_filter, 1, 1, 1, 4)

        filter_layout.addWidget(QLabel("Тип торговли:"), 2, 0)
        self.trade_type = QComboBox()
        self.trade_type.addItems(["Все", "Только спот", "Только фьючерсы"])
        self.trade_type.setMinimumHeight(36)
        filter_layout.addWidget(self.trade_type, 2, 1)

        self.exclusive_check = QCheckBox("Только на выбранных биржах")
        self.exclusive_check.setToolTip("Показывать только монеты, которые есть ТОЛЬКО на выбранных биржах")
        filter_layout.addWidget(self.exclusive_check, 2, 2, 1, 1)

        self.favorites_only_check = QCheckBox("Только избранное")
        self.favorites_only_check.setToolTip("Показывать только тикеры из избранного")
        filter_layout.addWidget(self.favorites_only_check, 2, 3, 1, 1)

        search_btn = QPushButton("Найти")
        search_btn.setMinimumHeight(36)
        search_btn.clicked.connect(self.apply_filter)
        filter_layout.addWidget(search_btn, 2, 4)

        reset_btn = QPushButton("Сбросить фильтры")
        reset_btn.setMinimumHeight(36)
        reset_btn.clicked.connect(self.reset_filters)
        filter_layout.addWidget(reset_btn, 2, 5)

        search_layout.addLayout(filter_layout)

        self.export_btn = QPushButton("Экспорт отфильтрованных тикеров")
        self.export_btn.setMinimumHeight(36)
        self.export_btn.clicked.connect(self.export_filtered_tickers)
        search_layout.addWidget(self.export_btn)

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Монета", "Спотовые биржи", "Фьючерсные биржи", "sortKey"])
        self.table.setColumnHidden(3, True)
        self.table.setSortingEnabled(True)
        self.table.sortItems(3, Qt.AscendingOrder)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.table.setMinimumHeight(400)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.ExtendedSelection)  # мультивыбор
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setSectionResizeMode(QHeaderView.Fixed)
        self.table.verticalHeader().setDefaultSectionSize(40)
        self.table.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.table.setHorizontalScrollMode(QAbstractItemView.ScrollPerPixel)

        search_layout.addWidget(self.table, 1)
        main_layout.addWidget(search_group, 1)

    # --- metascalp icons ---
    def _ensure_metascalp_icons(self):
        """Гарантированно создаёт self._icon_allowed/_icon_deny один раз."""
        if not hasattr(self, "_icon_allowed"):
            self._icon_allowed = QIcon("icons/allowed.png") if os.path.exists("icons/allowed.png") else None
            self._icon_deny = QIcon("icons/deny.png") if os.path.exists("icons/deny.png") else None

    def _load_metascalp_icons(self):
        """Старый метод остаётся для совместимости, но теперь сначала ensure."""
        self._ensure_metascalp_icons()
        if hasattr(self, "metascalp_btn"):
            self._apply_metascalp_icon(self.metascalp_btn, True)

    def _apply_metascalp_icon(self, btn: QPushButton, allowed: bool):
        # ▼ добавили защиту: если иконки ещё не созданы — создаём
        self._ensure_metascalp_icons()

        btn.setProperty("metascalp_allowed", allowed)
        btn.setStyleSheet("QPushButton { background: transparent; border: none; padding: 0; }")
        if allowed:
            if self._icon_allowed:
                btn.setIcon(self._icon_allowed)
                btn.setText("")
            else:
                btn.setText("A")
        else:
            if self._icon_deny:
                btn.setIcon(self._icon_deny)
                btn.setText("")
            else:
                btn.setText("X")
        btn.setIconSize(QSize(18, 18))

    def _toggle_metascalp(self, *_):
        btn = self.sender()
        if not isinstance(btn, QPushButton):
            return
        state = bool(btn.property("metascalp_allowed"))
        self._apply_metascalp_icon(btn, not state)

    def update_exchange_list(self):
        exchanges = self.get_unique_exchanges()
        self.exchange_filter.set_exchanges(exchanges)

    def get_unique_exchanges(self):
        exchanges = set()
        for coin in self.db.search_coins():
            if coin.spot_exchanges:
                for exchange in coin.spot_exchanges.split(','):
                    exchange_name = exchange.strip()
                    if exchange_name:
                        exchanges.add(exchange_name)
            if coin.futures_exchanges:
                for exchange in coin.futures_exchanges.split(','):
                    exchange_name = exchange.strip()
                    if exchange_name:
                        exchanges.add(exchange_name)
        return sorted(exchanges) if exchanges else []

    def start_scan(self):
        try:
            if hasattr(self, 'scan_thread') and hasattr(self.scan_thread, 'parser'):
                try:
                    self.scan_thread.parser.reset()
                except:
                    pass

            coin_name = self.coin_input.text().strip().upper()
            if not coin_name:
                QMessageBox.warning(self, "Ошибка", "Введите название монеты")
                return
            if not re.match(r"^[A-Z0-9.]{2,15}$", coin_name):
                QMessageBox.warning(self, "Ошибка", "Некорректное название монеты")
                return

            self.single_star_btn.setVisible(False)
            self.copy_btn.setVisible(False)
            self.metascalp_btn.setVisible(False)

            self.scan_btn.setEnabled(False)
            self.load_file_btn.setEnabled(False)
            self.coin_name_value.setText("")
            self.spot_value.setText("")
            self.futures_value.setText("")
            self.progress_bar.setVisible(True)
            self.batch_progress_bar.setVisible(False)

            thread_id = f"scan_{int(time.time())}_{id(self)}"
            self.scan_thread = ParseThread(coin_name, thread_id)
            self.scan_thread.finished.connect(self.on_scan_finished)
            self.scan_thread.error.connect(self.on_scan_error)
            self.scan_thread.start()

        except Exception as e:
            self.progress_bar.setVisible(False)
            self.scan_btn.setEnabled(True)
            self.load_file_btn.setEnabled(True)
            QMessageBox.critical(self, "Ошибка", f"Непредвиденная ошибка: {str(e)}")

    def load_file(self):
        if hasattr(self, 'batch_thread') and hasattr(self.batch_thread, 'parser'):
            try:
                self.batch_thread.parser.reset()
            except:
                pass

        file_path, _ = QFileDialog.getOpenFileName(
            self, "Выберите файл с монетами", "", "Text Files (*.txt);;All Files (*)"
        )
        if not file_path:
            return

        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                coin_names = f.readlines()
            coin_names = [name.strip().upper() for name in coin_names if name.strip()]
            if not coin_names:
                QMessageBox.warning(self, "Ошибка", "Файл пуст")
                return

            original_text = self.coin_input.text()

            self.scan_btn.setEnabled(False)
            self.load_file_btn.setEnabled(False)
            self.progress_bar.setVisible(False)
            self.batch_progress_bar.setVisible(True)
            self.batch_progress_bar.setRange(0, len(coin_names))
            self.batch_progress_bar.setValue(0)
            self.batch_progress_bar.setFormat("Подготовка к сканирование...")
            self.cancel_btn.setVisible(True)

            coin_count = len(coin_names)
            max_workers = min(5, max(2, coin_count // 20))

            thread_id = f"batch_{int(time.time())}_{id(self)}"
            self.batch_thread = BatchParseThread(coin_names, self.db, thread_id, max_workers)
            self.batch_thread.progress.connect(self.on_batch_progress)
            self.batch_thread.finished.connect(self.on_batch_finished)
            self.batch_thread.error.connect(self.on_batch_error)
            self.batch_thread.start()

            self.start_memory_cleanup()

            self.coin_input.setText(original_text)

        except Exception as e:
            QMessageBox.critical(self, "Ошибка", f"Не удалось загрузить файл: {str(e)}")
            self.scan_btn.setEnabled(True)
            self.load_file_btn.setEnabled(True)
            self.stop_memory_cleanup()

    def on_scan_finished(self, data):
        try:
            self.progress_bar.setVisible(False)
            self.scan_btn.setEnabled(True)
            self.load_file_btn.setEnabled(True)
            self.coin_name_value.setText(data['name'])
            self.spot_value.setText(", ".join(data['spot']) if data['spot'] else "Нет данных")
            self.futures_value.setText(", ".join(data['futures']) if data['futures'] else "Нет данных")

            # делаем служебные кнопки видимыми
            self.copy_btn.setVisible(True)
            self.metascalp_btn.setVisible(True)
            self.single_star_btn.setVisible(True)

            spot_str = ", ".join(data['spot'])
            futures_str = ", ".join(data['futures'])

            # сохраняем в БД и подтягиваем признак избранного
            if hasattr(self, 'db') and self.db is not None:
                self.db.save_coin(data['name'], spot_str, futures_str)
                # прочитаем favorite для этой монеты
                fav = False
                for c in self.db.search_coins():
                    if c.name == data['name']:
                        fav = bool(c.favorite)
                        break
                # синхронизируем кнопку⭐
                self.single_star_btn.blockSignals(True)
                self.single_star_btn.setChecked(fav)
                self.single_star_btn.setIcon(self._star_icon_yellow if fav else self._star_icon_grey)
                self.single_star_btn.blockSignals(False)

                self.update_exchange_list()
                self.reset_filters()
                QMessageBox.information(self, "Успех", "Данные сохранены в базу данных!")
            else:
                self.db = Database(self.profile_name)
                self.db.save_coin(data['name'], spot_str, futures_str)
                self.update_exchange_list()
                self.reset_filters()
                QMessageBox.warning(self, "Внимание", "База данных была переинициализирована")

        except Exception as e:
            self.progress_bar.setVisible(False)
            self.scan_btn.setEnabled(True)
            self.load_file_btn.setEnabled(True)
            QMessageBox.critical(self, "Ошибка", f"Ошибка при сохранении данных: {str(e)}")

    def on_scan_error(self, error_msg):
        self.progress_bar.setVisible(False)
        self.scan_btn.setEnabled(True)
        self.load_file_btn.setEnabled(True)
        self.copy_btn.setVisible(False)
        self.metascalp_btn.setVisible(False)
        self.single_star_btn.setVisible(False)
        QMessageBox.critical(self, "Ошибка сканирования", error_msg)

    def on_batch_progress(self, current, total, coin_name, remaining_time):
        self.batch_progress_bar.setValue(current)
        self.batch_progress_bar.setFormat(f"Сканирование: {coin_name} ({current}/{total}) - Осталось: {remaining_time}")

    def on_batch_finished(self):
        self.scan_btn.setEnabled(True)
        self.load_file_btn.setEnabled(True)
        self.batch_progress_bar.setVisible(False)
        self.batch_progress_bar.setFormat("")
        self.cancel_btn.setVisible(False)

        self.stop_memory_cleanup()

        self.db.reload_from_file()
        self.update_exchange_list()
        self.reset_filters()

        QMessageBox.information(self, "Успех", "Пакетное сканирование завершено!")

    def on_batch_error(self, error_msg, coin_name):
        QMessageBox.critical(self, "Ошибка сканирования", f"Ошибка при сканировании {coin_name}:\n{error_msg}")

    def cancel_batch_scan(self):
        if hasattr(self, 'batch_thread') and self.batch_thread.isRunning():
            self.batch_thread.cancel()
            self.batch_thread.quit()
            self.batch_thread.wait(1000)
            self.on_batch_finished()
            self.batch_progress_bar.setFormat("")
            self.stop_memory_cleanup()

    def apply_filter(self):
        coin_name = self.coin_search_input.text().strip().upper()
        trade_type_text = self.trade_type.currentText()
        exclusive_mode = self.exclusive_check.isChecked()
        favorites_only = getattr(self, 'favorites_only_check', None) and self.favorites_only_check.isChecked()

        selected_exchanges = self.exchange_filter.get_selected_items()
        if not selected_exchanges:
            selected_exchanges = self.get_unique_exchanges()

        trade_type = {
            "Все": "all",
            "Только спот": "spot",
            "Только фьючерсы": "futures"
        }.get(trade_type_text, "all")

        results = self.db.search_coins()
        filtered_results = []

        for coin in results:
            if coin_name and coin_name not in coin.name:
                continue

            coin_spot_exchanges = []
            if coin.spot_exchanges:
                coin_spot_exchanges = [e.strip() for e in coin.spot_exchanges.split(',') if e.strip()]

            coin_futures_exchanges = []
            if coin.futures_exchanges:
                coin_futures_exchanges = [e.strip() for e in coin.futures_exchanges.split(',') if e.strip()]

            all_coin_exchanges = set(coin_spot_exchanges + coin_futures_exchanges)

            if exclusive_mode:
                found_on_all = True
                for exchange in selected_exchanges:
                    if trade_type == "all":
                        if exchange not in coin_spot_exchanges and exchange not in coin_futures_exchanges:
                            found_on_all = False
                            break
                    elif trade_type == "spot":
                        if exchange not in coin_spot_exchanges:
                            found_on_all = False
                            break
                    elif trade_type == "futures":
                        if exchange not in coin_futures_exchanges:
                            found_on_all = False
                            break
                if not found_on_all:
                    continue
                if not all_coin_exchanges.issubset(set(selected_exchanges)):
                    continue
            else:
                found = False
                for exchange in selected_exchanges:
                    if trade_type == "all":
                        if exchange in coin_spot_exchanges or exchange in coin_futures_exchanges:
                            found = True
                            break
                    elif trade_type == "spot":
                        if exchange in coin_spot_exchanges:
                            found = True
                            break
                    elif trade_type == "futures":
                        if exchange in coin_futures_exchanges:
                            found = True
                            break
                if not found:
                    continue

            if trade_type == "spot" and not coin_spot_exchanges:
                continue
            if trade_type == "futures" and not coin_futures_exchanges:
                continue

            if favorites_only and not getattr(coin, 'favorite', False):
                continue

            filtered_results.append(coin)

        # Избранные вверх, затем по имени
        filtered_results.sort(key=lambda c: (not getattr(c, 'favorite', False), c.name))
        self.filtered_results = filtered_results

        # Быстрый рефреш таблицы (без мерцаний)
        self.table.setUpdatesEnabled(False)
        self.table.setSortingEnabled(False)
        try:
            self.table.clearContents()
            self.table.setRowCount(len(filtered_results))
            for row_idx, coin in enumerate(filtered_results):
                coin_widget = QWidget()
                coin_layout = QHBoxLayout(coin_widget)
                coin_layout.setContentsMargins(8, 0, 8, 0)
                coin_layout.setSpacing(6)

                # Кнопка-звезда слева
                star_btn = QPushButton()
                star_btn.setCheckable(True)
                star_btn.setChecked(getattr(coin, 'favorite', False))
                star_btn.setFixedSize(24, 24)
                star_btn.setStyleSheet("""
                    QPushButton {
                        background-color: transparent;
                        border: none;
                        padding: 0px;
                        margin: 0px;
                    }
                """)
                star_btn.setIcon(self._star_icon_yellow if star_btn.isChecked() else self._star_icon_grey)
                star_btn.setIconSize(QSize(18, 18))

                def _on_star_toggled(checked, n=coin.name, btn=star_btn):
                    self.toggle_favorite(n, checked)
                    btn.setIcon(self._star_icon_yellow if checked else self._star_icon_grey)

                star_btn.toggled.connect(_on_star_toggled)

                coin_label = QLabel(coin.name)
                coin_label.setObjectName("coin_name_label")  # <— чтобы надёжно находить строку
                coin_label.setFont(QFont("Arial", 10, QFont.Bold))
                coin_label.setStyleSheet("background-color: transparent;")
                coin_label.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Preferred)

                copy_btn = QPushButton()
                copy_btn.setFixedSize(24, 24)
                copy_btn.setStyleSheet("""
                    QPushButton {
                        background-color: #6A5AF9;
                        border: none;
                        border-radius: 12px;
                    }
                    QPushButton:hover {
                        background-color: #5B4AE9;
                    }
                """)
                if os.path.exists("icons/icon_copy.png"):
                    copy_btn.setIcon(QIcon("icons/icon_copy.png"))
                    copy_btn.setIconSize(QSize(16, 16))
                else:
                    copy_btn.setText("C")
                copy_btn.setToolTip("Копировать название")
                copy_btn.clicked.connect(lambda _, name=coin.name: self.copy_coin_name_from_table(name))

                coin_layout.addWidget(star_btn)
                coin_layout.addWidget(coin_label)
                coin_layout.addSpacing(8)
                coin_layout.addWidget(copy_btn)

                # ▼ новая плоская allow/deny-иконка без кружка
                row_metascalp_btn = QPushButton()
                row_metascalp_btn.setFixedSize(24, 24)
                row_metascalp_btn.setCheckable(True)
                self._apply_metascalp_icon(row_metascalp_btn, True)  # по умолчанию allowed.png
                row_metascalp_btn.clicked.connect(self._toggle_metascalp)
                coin_layout.addWidget(row_metascalp_btn)

                coin_layout.addStretch()

                self.table.setCellWidget(row_idx, 0, coin_widget)

                spot_item = QTableWidgetItem(coin.spot_exchanges or "")
                spot_item.setToolTip(coin.spot_exchanges or "")
                self.table.setItem(row_idx, 1, spot_item)

                futures_item = QTableWidgetItem(coin.futures_exchanges or "")
                futures_item.setToolTip(coin.futures_exchanges or "")
                self.table.setItem(row_idx, 2, futures_item)
                sort_key = f"{0 if getattr(coin, 'favorite', False) else 1}_{coin.name}"
                sort_item = QTableWidgetItem(sort_key)
                sort_item.setFlags(Qt.ItemIsEnabled)  # не редактируется
                self.table.setItem(row_idx, 3, sort_item)
        finally:
            self.table.setSortingEnabled(True)
            self.table.sortItems(3, Qt.AscendingOrder)
            self.table.setUpdatesEnabled(True)

    def reset_filters(self):
        self.coin_search_input.clear()
        self.trade_type.setCurrentIndex(0)
        self.exclusive_check.setChecked(False)
        self.favorites_only_check.setChecked(False)
        self.exchange_filter.set_exchanges(self.get_unique_exchanges())
        self.apply_filter()

    def copy_coin_name(self, button):
        coin_name = self.coin_name_value.text()
        if coin_name:
            pyperclip.copy(f"{coin_name}USDT")
            self.copy_notification.show_notification(button)

    def copy_coin_name_from_table(self, name):
        pyperclip.copy(f"{name}USDT")
        for i in range(self.table.rowCount()):
            widget = self.table.cellWidget(i, 0)
            if widget:
                copy_btn = None
                # найдём кнопку копирования внутри ячейки (второй QPushButton после звезды)
                buttons = widget.findChildren(QPushButton)
                if len(buttons) >= 2:
                    copy_btn = buttons[1]
                if copy_btn and copy_btn == self.sender():
                    self.table.selectRow(i)
                    self.copy_notification.show_notification(copy_btn)
                    break

    def export_filtered_tickers(self):
        if not hasattr(self, 'filtered_results') or not self.filtered_results:
            QMessageBox.warning(self, "Ошибка", "Нет отфильтрованных данных для экспорта")
            return

        file_path, _ = QFileDialog.getSaveFileName(
            self, "Сохранить тикеры", "", "Text Files (*.txt)"
        )
        if not file_path:
            return

        try:
            with open(file_path, 'w', encoding='utf-8') as f:
                for coin in self.filtered_results:
                    f.write(f"{coin.name}\n")
            QMessageBox.information(self, "Успех", f"Тикеры сохранены в файл: {file_path}")
        except Exception as e:
            QMessageBox.critical(self, "Ошибка", f"Ошибка при сохранении файла: {str(e)}")

    def delete_coin_by_name(self, name: str):
        reply = QMessageBox.question(
            self,
            "Подтверждение удаления",
            f"Вы действительно хотите удалить {name} из списка?",
            QMessageBox.Yes | QMessageBox.No
        )
        if reply == QMessageBox.Yes:
            try:
                if self.db.delete_coin(name):
                    self.update_exchange_list()
                    # удалим строку из таблицы и кэша, без полной перерисовки
                    row = self._find_row_by_name(name)
                    if row is not None:
                        self.table.setUpdatesEnabled(False)
                        try:
                            self.table.removeRow(row)
                            self.filtered_results = [c for c in self.filtered_results if c.name != name]
                        finally:
                            self.table.setUpdatesEnabled(True)
                    QMessageBox.information(self, "Удалено", f"{name} удалён из базы.")
                else:
                    QMessageBox.information(self, "Информация", f"{name} не найден в базе.")
            except Exception as e:
                QMessageBox.critical(self, "Ошибка", f"Не удалось удалить {name}: {str(e)}")

    def delete_selected_coins(self):
        # собрать выбранные строки (уникальные индексы)
        rows = sorted({i.row() for i in self.table.selectedIndexes()})
        if not rows:
            return
        names = []
        for r in rows:
            w = self.table.cellWidget(r, 0)
            if not w:
                continue
            lbl = w.findChild(QLabel, "coin_name_label")
            if lbl:
                names.append(lbl.text())
        if not names:
            return
        reply = QMessageBox.question(
            self,
            "Подтверждение удаления",
            f"Вы уверены, что хотите удалить выделенные тикеры? ({len(names)} шт.)",
            QMessageBox.Yes | QMessageBox.No
        )
        if reply != QMessageBox.Yes:
            return
        self.table.setUpdatesEnabled(False)
        try:
            for name in names:
                try:
                    self.db.delete_coin(name)
                except Exception:
                    pass
            # пересобрать таблицу
            self.update_exchange_list()
            self.apply_filter()
        finally:
            self.table.setUpdatesEnabled(True)
        QMessageBox.information(self, "Готово", f"Удалено: {len(names)}")

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_C and (event.modifiers() & Qt.ControlModifier):
            selected_items = self.table.selectedItems()
            if selected_items:
                row = selected_items[0].row()
                if 0 <= row < len(self.filtered_results):
                    coin_name = self.filtered_results[row].name
                    pyperclip.copy(f"{coin_name}USDT")
                    rect = self.table.visualItemRect(selected_items[0])
                    pos = self.table.mapToGlobal(rect.topLeft())
                    self.copy_notification.show_notification_at_pos(pos)

        elif event.key() == Qt.Key_Delete:
            # если выбрано много — удалим списком
            if len({i.row() for i in self.table.selectedIndexes()}) > 1:
                self.delete_selected_coins()
            else:
                selected_items = self.table.selectedItems()
                if selected_items:
                    row = selected_items[0].row()
                    if 0 <= row < len(self.filtered_results):
                        coin_name = self.filtered_results[row].name
                        self.delete_coin_by_name(coin_name)

        super().keyPressEvent(event)

    # ------- ИЗБРАННОЕ: быстрая смена и перенос строки без полной перерисовки -------

    def toggle_favorite(self, name: str, is_favorite: bool):
        try:
            # 1) пишем в БД
            if hasattr(self, 'db') and self.db:
                self.db.set_favorite(name, is_favorite)

            # 2) обновляем кэш
            for c in self.filtered_results:
                if c.name == name:
                    c.favorite = bool(is_favorite)
                    break

            # 3) синхронизируем строку таблицы (иконка⭐, sort key)
            row = self._find_row_by_name(name)

            # фильтр «только избранное»
            if hasattr(self, 'favorites_only_check') and self.favorites_only_check.isChecked():
                if not is_favorite and row is not None:
                    self.table.removeRow(row)
                    self.filtered_results = [c for c in self.filtered_results if c.name != name]
                    return
                if is_favorite and row is None:
                    self.apply_filter()
                    return

            if row is not None:
                w = self.table.cellWidget(row, 0)
                if w:
                    for b in w.findChildren(QPushButton):
                        if b.isCheckable():
                            b.blockSignals(True)
                            b.setChecked(is_favorite)
                            b.setIcon(self._star_icon_yellow if is_favorite else self._star_icon_grey)
                            b.blockSignals(False)
                            break

                key_item = self.table.item(row, 3)
                if key_item is None:
                    key_item = QTableWidgetItem()
                    key_item.setFlags(Qt.ItemIsEnabled)
                    self.table.setItem(row, 3, key_item)
                key_item.setText(f"{0 if is_favorite else 1}_{name}")
                self.table.sortItems(3, Qt.AscendingOrder)
            else:
                self.apply_filter()

        except Exception as e:
            QMessageBox.warning(self, "Ошибка", f"Не удалось изменить избранное для {name}: {str(e)}")

    def toggle_favorite_single(self, checked: bool):
        """Клик по ⭐ в одиночном блоке: пишем в БД, синхроним таблицу и саму кнопку."""
        name = self.coin_name_value.text().strip()
        if not name:
            return
        try:
            self.toggle_favorite(name, bool(checked))
            self.single_star_btn.setIcon(self._star_icon_yellow if checked else self._star_icon_grey)
        except Exception as e:
            QMessageBox.warning(self, "Ошибка", f"Не удалось изменить избранное для {name}: {str(e)}")
            self.single_star_btn.blockSignals(True)
            self.single_star_btn.setChecked(not checked)
            self.single_star_btn.setIcon(self._star_icon_yellow if self.single_star_btn.isChecked() else self._star_icon_grey)
            self.single_star_btn.blockSignals(False)

    def _find_row_by_name(self, name: str):
        for i in range(self.table.rowCount()):
            w = self.table.cellWidget(i, 0)
            if not w:
                continue
            lbl = w.findChild(QLabel, "coin_name_label")
            if lbl and lbl.text() == name:
                return i
        return None

    # ------- ИКОНКИ ЗВЕЗДЫ: контур + заливка -------

    def _build_star_icons_from_outline(self):
        path = "icons/icon_star.png"
        base = QPixmap(path)
        if base.isNull():
            self._star_icon_grey = QIcon()
            self._star_icon_yellow = QIcon()
            return

        # серая — просто окрашенный контур
        self._star_icon_grey = self._tint_outline(base, QColor("#777777"))

        # жёлтая — заливка звездой + контур сверху
        filled = QPixmap(base.size())
        filled.fill(Qt.transparent)

        self._paint_star_fill(filled, QColor("#FFD700"))  # заливка
        painter = QPainter(filled)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setCompositionMode(QPainter.CompositionMode_SourceOver)
        painter.drawPixmap(0, 0, self._tinted_pixmap(base, QColor("#FFC107")))  # контур
        painter.end()

        self._star_icon_yellow = QIcon(filled)

    def _tinted_pixmap(self, pix: QPixmap, color: QColor) -> QPixmap:
        result = QPixmap(pix.size())
        result.fill(Qt.transparent)
        p = QPainter(result)
        p.fillRect(result.rect(), color)
        p.setCompositionMode(QPainter.CompositionMode_DestinationIn)
        p.drawPixmap(0, 0, pix)
        p.end()
        return result

    def _tint_outline(self, pix: QPixmap, color: QColor) -> QIcon:
        return QIcon(self._tinted_pixmap(pix, color))

    def _paint_star_fill(self, target: QPixmap, fill_color: QColor):
        w, h = target.width(), target.height()
        cx, cy = w / 2.0, h / 2.0
        margin = min(w, h) * 0.12
        r_outer = (min(w, h) / 2.0) - margin
        r_inner = r_outer * 0.5

        pts = []
        for i in range(10):
            angle = (math.pi / 2) + i * (math.pi / 5)
            r = r_outer if i % 2 == 0 else r_inner
            x = cx + r * math.cos(angle)
            y = cy - r * math.sin(angle)
            pts.append(QPointF(x, y))

        poly = QPolygonF(pts)
        p = QPainter(target)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(fill_color))
        p.drawPolygon(poly)
        p.end()


CLICKER_OPENED = False


class CryptoApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.renaming_tab_index = -1
        self.rename_edit = None
        self.is_renaming = False

        self.init_ui()
        self.apply_theme()
        self.always_on_top = False
        self.setWindowTitle("Crypto Shah Scanner")
        self.setWindowIcon(QIcon("icons/crypto_icon.png"))
        self.clicker_window = None

    def init_ui(self):
        self.setMinimumSize(1000, 900)

        central_widget = QWidget()
        central_widget.setObjectName("central_widget")
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        header = QWidget()
        header.setFixedHeight(50)
        header.setStyleSheet("background-color: #333333;")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(20, 0, 20, 0)

        logo_layout = QHBoxLayout()
        logo_label = QLabel("Crypto Shah Scanner")
        logo_label.setStyleSheet("""
            font-size: 18px;
            font-weight: bold;
            color: #DDDDDD;
            letter-spacing: 1px;
        """)
        logo_layout.addWidget(logo_label)
        header_layout.addLayout(logo_layout)

        header_layout.addStretch()

        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(10)

        self.new_tab_btn = QPushButton("+")
        self.new_tab_btn.setFixedSize(36, 36)
        self.new_tab_btn.setToolTip("Новая вкладка")
        self.new_tab_btn.setStyleSheet("""
            QPushButton {
                background-color: #444444;
                color: #DDDDDD;
                border: none;
                border-radius: 18px;
                font-size: 18px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #555555;
            }
        """)
        self.new_tab_btn.clicked.connect(self.show_new_tab_menu)
        btn_layout.addWidget(self.new_tab_btn)

        self.copy_profile_btn = QPushButton("⎘")
        self.copy_profile_btn.setFixedSize(36, 36)
        self.copy_profile_btn.setToolTip("Копировать текущий профиль")
        self.copy_profile_btn.setStyleSheet("""
            QPushButton {
                background-color: #444444;
                color: #DDDDDD;
                border: none;
                border-radius: 18px;
                font-size: 18px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #555555;
            }
        """)
        self.copy_profile_btn.clicked.connect(self.copy_current_profile)

        self.delete_profile_btn = QPushButton("✕")
        self.delete_profile_btn.setFixedSize(36, 36)
        self.delete_profile_btn.setToolTip("Удалить текущий профиль")
        self.delete_profile_btn.setStyleSheet("""
            QPushButton {
                background-color: #FF5555;
                color: #DDDDDD;
                border: none;
                border-radius: 18px;
                font-size: 18px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #FF3333;
            }
        """)
        self.delete_profile_btn.clicked.connect(self.delete_current_profile)

        btn_layout.addWidget(self.copy_profile_btn)
        btn_layout.addWidget(self.delete_profile_btn)

        self.freak_parser_btn = QPushButton()
        self.freak_parser_btn.setFixedSize(36, 36)
        self.freak_parser_btn.setToolTip("Открыть Freak Parser")
        if os.path.exists("icons/icon_freak_parser.png"):
            self.freak_parser_btn.setIcon(QIcon("icons/icon_freak_parser.png"))
            self.freak_parser_btn.setIconSize(QSize(24, 24))
        else:
            self.freak_parser_btn.setText("FP")
        self.freak_parser_btn.setStyleSheet("""
            QPushButton {
                background-color: #444444;
                border: none;
                border-radius: 18px;
            }
            QPushButton:hover {
                background-color: #555555;
            }
        """)
        self.freak_parser_btn.clicked.connect(self.open_freak_parser)
        btn_layout.addWidget(self.freak_parser_btn)

        self.pin_button = QPushButton()
        self.pin_button.setCheckable(True)
        self.pin_button.setFixedSize(36, 36)
        self.pin_button.setToolTip("Закрепить поверх всех окон")
        if os.path.exists("icons/pin_icon.png"):
            self.pin_button.setIcon(QIcon("icons/pin_icon.png"))
        else:
            self.pin_button.setText("📌")
        self.pin_button.setStyleSheet("""
            QPushButton {
                background-color: #444444;
                border: none;
                border-radius: 18px;
            }
            QPushButton:hover {
                background-color: #555555;
            }
            QPushButton:checked {
                background-color: #6A5AF9;
            }
        """)
        self.pin_button.toggled.connect(self.toggle_always_on_top)
        header_layout.addWidget(self.pin_button)

        self.clicker_btn = QPushButton()
        self.clicker_btn.setFixedSize(36, 36)
        self.clicker_btn.setToolTip("Открыть кликер")
        if os.path.exists("icons/icon_clicker.png"):
            self.clicker_btn.setIcon(QIcon("icons/icon_clicker.png"))
            self.clicker_btn.setIconSize(QSize(24, 24))
        else:
            self.clicker_btn.setText("C")
        self.clicker_btn.setStyleSheet("""
            QPushButton {
                background-color: #444444;
                border: none;
                border-radius: 18px;
            }
            QPushButton:hover {
                background-color: #555555;
            }
        """)
        self.clicker_btn.clicked.connect(self.open_clicker)
        header_layout.addWidget(self.clicker_btn)

        header_layout.addLayout(btn_layout)
        main_layout.addWidget(header)

        self.tab_widget = QTabWidget()
        self.tab_widget.setTabsClosable(True)
        self.tab_widget.tabCloseRequested.connect(self.close_tab)
        self.tab_widget.setMovable(True)

        close_icon_style = """
            QTabBar::close-button {
                image: url(icons/icon_X.png);
                subcontrol-position: right;
                padding: 3px;
                width: 16px;
                height: 16px;
            }
        """ if os.path.exists("icons/icon_X.png") else """
            QTabBar::close-button {
                background-color: #FF5555;
                border-radius: 8px;
                subcontrol-position: right;
                padding: 3px;
                width: 16px;
                height: 16px;
            }
        """

        self.tab_widget.setStyleSheet(f"""
            QTabWidget::pane {{
                border: none;
                background: #1E1E1E;
            }}
            QTabBar::tab {{
                background: #3A3A3A;
                color: #DDDDDD;
                padding: 10px 20px;
                border-top-left-radius: 8px;
                border-top-right-radius: 8px;
                margin-right: 2px;
                font-size: 12px;
                min-width: 150px;
            }}
            QTabBar::tab:selected {{
                background: #444444;
                color: #6A5AF9;
                border-bottom: 2px solid #6A5AF9;
            }}
            {close_icon_style}
        """)

        self.tab_widget.tabBar().installEventFilter(self)
        QApplication.instance().installEventFilter(self)

        main_layout.addWidget(self.tab_widget, 1)

    def open_freak_parser(self):
        if hasattr(self, 'freak_parser_window') and self.freak_parser_window is not None:
            try:
                if self.freak_parser_window.isVisible():
                    self.freak_parser_window.raise_()
                    self.freak_parser_window.activateWindow()
                    return
                else:
                    self.freak_parser_window = None
            except:
                self.freak_parser_window = None

        if not hasattr(self, 'freak_parser_window') or self.freak_parser_window is None:
            try:
                from freak_parser import TradingViewParserGUI
                self.freak_parser_window = TradingViewParserGUI()
                self.freak_parser_window.finished.connect(lambda: setattr(self, 'freak_parser_window', None))
                self.freak_parser_window.show()
            except Exception as e:
                print(f"Ошибка при открытии Freak Parser: {e}")
                self.freak_parser_window = None

    def open_clicker(self):
        global CLICKER_OPENED
        if CLICKER_OPENED:
            QMessageBox.information(self, "Информация", "Кликер уже открыт!")
            return
        self.clicker_window = ClickerWindow()
        self.clicker_window.show()
        CLICKER_OPENED = True
        self.clicker_window.destroyed.connect(self.on_clicker_closed)

    def on_clicker_closed(self):
        global CLICKER_OPENED
        CLICKER_OPENED = False

    def show_new_tab_menu(self):
        menu = QMenu(self)
        menu.setStyleSheet("""
            QMenu {
                background-color: #2D2D2D;
                color: #DDDDDD;
                border: 1px solid #444444;
                border-radius: 4px;
            }
            QMenu::item {
                padding: 5px 20px;
            }
            QMenu::item:selected {
                background-color: #6A5AF9;
            }
        """)

        new_action = menu.addAction("➕ Создать новый профиль")
        new_action.triggered.connect(self.create_new_profile)

        menu.addSeparator()

        profiles = Database.list_profiles()
        if not profiles:
            action = menu.addAction("Нет доступных профилей")
            action.setEnabled(False)
        else:
            for profile in profiles:
                action = menu.addAction(f"📁 {profile}")
                action.triggered.connect(lambda checked, p=profile: self.open_profile(p))

        menu.exec_(self.new_tab_btn.mapToGlobal(QPoint(0, self.new_tab_btn.height())))

    def open_profile(self, profile_name):
        for i in range(self.tab_widget.count()):
            if self.tab_widget.tabText(i) == profile_name:
                self.tab_widget.setCurrentIndex(i)
                return
        self.add_profile_tab(profile_name)

    def eventFilter(self, source, event):
        if (event.type() == QEvent.MouseButtonDblClick and source is self.tab_widget.tabBar()):
            index = source.tabAt(event.pos())
            if index >= 0:
                self.start_rename_tab(index)
                return True

        if (self.is_renaming and event.type() == QEvent.MouseButtonPress and source is not self.rename_edit):
            self.finish_rename_tab()
            return True

        if (self.is_renaming and source is self.rename_edit and event.type() == QEvent.FocusOut):
            self.finish_rename_tab()
            return True

        if (self.is_renaming and event.type() == QEvent.KeyPress and event.key() == Qt.Key_Escape):
            self.cancel_rename_tab()
            return True

        return super().eventFilter(source, event)

    def start_rename_tab(self, index):
        if self.rename_edit:
            self.finish_rename_tab()

        self.renaming_tab_index = index
        self.is_renaming = True
        old_name = self.tab_widget.tabText(index)

        self.rename_edit = QLineEdit(old_name)
        self.rename_edit.setStyleSheet("""
            QLineEdit {
                background-color: #FFFFFF;
                color: #000000;
                border: 2px solid #6A5AF9;
                border-radius: 4px;
                padding: 4px;
            }
        """)
        self.rename_edit.selectAll()
        self.rename_edit.returnPressed.connect(self.finish_rename_tab)

        self.tab_widget.tabBar().setTabButton(index, QTabBar.LeftSide, None)
        self.tab_widget.tabBar().setTabButton(index, QTabBar.RightSide, None)
        self.tab_widget.tabBar().setTabText(index, "")

        tab_rect = self.tab_widget.tabBar().tabRect(index)
        self.rename_edit.setParent(self.tab_widget.tabBar())
        self.rename_edit.setGeometry(tab_rect)
        self.rename_edit.show()
        self.rename_edit.setFocus()

    def finish_rename_tab(self):
        if self.renaming_tab_index >= 0 and self.rename_edit:
            new_name = self.rename_edit.text().strip()
            old_name = self.tab_widget.tabText(self.renaming_tab_index)

            if new_name and new_name != old_name:
                unique = True
                for i in range(self.tab_widget.count()):
                    if i != self.renaming_tab_index and self.tab_widget.tabText(i) == new_name:
                        unique = False
                        break

                if unique:
                    self.tab_widget.setTabText(self.renaming_tab_index, new_name)
                    try:
                        tab = self.tab_widget.widget(self.renaming_tab_index)
                        if hasattr(tab, 'db'):
                            try:
                                tab.db.rename_profile(new_name)
                                tab.profile_name = new_name
                            except Exception as e:
                                QMessageBox.warning(self, "Ошибка", f"Не удалось переименовать профиль: {str(e)}")
                                self.tab_widget.setTabText(self.renaming_tab_index, old_name)
                                return

                    except Exception as e:
                        QMessageBox.warning(self, "Ошибка", f"Не удалось переименовать профиль: {str(e)}")
                        self.tab_widget.setTabText(self.renaming_tab_index, old_name)

            self.restore_tab_buttons(self.renaming_tab_index)

            try:
                if self.rename_edit:
                    self.rename_edit.hide()
                    self.rename_edit.deleteLater()
            except:
                pass

            self.rename_edit = None
            self.renaming_tab_index = -1
            self.is_renaming = False

    def cancel_rename_tab(self):
        if self.renaming_tab_index >= 0:
            old_name = self.tab_widget.tabText(self.renaming_tab_index)
            self.tab_widget.setTabText(self.renaming_tab_index, old_name)
            self.restore_tab_buttons(self.renaming_tab_index)
            try:
                if self.rename_edit:
                    self.rename_edit.hide()
                    self.rename_edit.deleteLater()
            except:
                pass
            self.rename_edit = None
            self.renaming_tab_index = -1
            self.is_renaming = False

    def restore_tab_buttons(self, index):
        self.tab_widget.setTabsClosable(False)
        self.tab_widget.setTabsClosable(True)

    def apply_theme(self):
        self.setStyleSheet("""
            QMainWindow {
                background-color: #1E1E1E;
            }
            #central_widget {
                background-color: #1E1E1E;
            }
            QToolTip {
                background-color: #3A3A3A;
                color: #DDDDDD;
                border: 1px solid #555555;
                border-radius: 4px;
                padding: 5px;
            }
        """)

    def add_profile_tab(self, profile_name):
        for i in range(self.tab_widget.count()):
            if self.tab_widget.tabText(i) == profile_name:
                self.tab_widget.setCurrentIndex(i)
                return
        tab = ProfileTab(profile_name)
        index = self.tab_widget.addTab(tab, profile_name)
        self.tab_widget.setCurrentIndex(index)
        return tab

    def create_new_profile(self, name=None):
        if not name:
            name, ok = QInputDialog.getText(
                self,
                "Новый профиль",
                "Введите имя профиля:",
                text=f"Профиль {self.tab_widget.count() + 1}"
            )
            if not ok or not name:
                return

        for i in range(self.tab_widget.count()):
            if self.tab_widget.tabText(i) == name:
                QMessageBox.warning(self, "Ошибка", "Профиль с таким именем уже открыт!")
                return

        db = Database(name)
        db.save()
        self.add_profile_tab(name)

    def copy_current_profile(self):
        current_index = self.tab_widget.currentIndex()
        if current_index < 0:
            return
        current_name = self.tab_widget.tabText(current_index)
        new_name, ok = QInputDialog.getText(
            self,
            "Копировать профиль",
            "Введите имя для копии:",
            text=f"{current_name} (копия)"
        )
        if not ok or not new_name:
            return
        for i in range(self.tab_widget.count()):
            if self.tab_widget.tabText(i) == new_name:
                QMessageBox.warning(self, "Ошибка", "Профиль с таким именем уже открыт!")
                return

        current_db = Database(current_name)
        new_db = current_db.copy_profile(new_name)
        self.add_profile_tab(new_name)

    def delete_current_profile(self):
        current_index = self.tab_widget.currentIndex()
        if current_index < 0:
            return
        if self.tab_widget.count() <= 1:
            QMessageBox.warning(self, "Ошибка", "Нельзя удалить последний профиль!")
            return

        profile_name = self.tab_widget.tabText(current_index)
        reply = QMessageBox.question(
            self,
            "Подтверждение удаления",
            f"Вы уверены, что хотите удалить профиль '{profile_name}'? Это действие нельзя отменить.",
            QMessageBox.Yes | QMessageBox.No
        )
        if reply == QMessageBox.No:
            return

        try:
            db = Database(profile_name)
            db.delete_profile()
        except Exception as e:
            QMessageBox.warning(self, "Ошибка", f"Не удалось удалить файл профиля: {str(e)}")

        widget = self.tab_widget.widget(current_index)
        widget.deleteLater()
        self.tab_widget.removeTab(current_index)

    def close_tab(self, index):
        widget = self.tab_widget.widget(index)
        widget.deleteLater()
        self.tab_widget.removeTab(index)

    def toggle_always_on_top(self, checked):
        self.always_on_top = checked
        self.setWindowFlag(Qt.WindowStaysOnTopHint, checked)
        self.show()
        if checked:
            self.pin_button.setStyleSheet("""
                QPushButton {
                    background-color: #6A5AF9;
                    border: none;
                    border-radius: 18px;
                }
                QPushButton:hover {
                    background-color: #5B4AE9;
                }
            """)
        else:
            self.pin_button.setStyleSheet("""
                QPushButton {
                    background-color: #444444;
                    border: none;
                    border-radius: 18px;
                }
                QPushButton:hover {
                    background-color: #555555;
                }
            """)

    def closeEvent(self, event):
        super().closeEvent(event)


if __name__ == "__main__":
    import multiprocessing as mp
    mp.freeze_support()

    if len(sys.argv) > 1 and sys.argv[1] == "--worker":
        if len(sys.argv) < 3:
            print(json.dumps({"error": "Не указано название монеты"}))
            sys.exit(1)

        coin_name = sys.argv[2]
        try:
            result = parse_coin_in_process(coin_name, headless=True)
            print(json.dumps(result))
        except Exception as e:
            print(json.dumps({"error": str(e), "coin": coin_name}))
        sys.exit(0)

    if not setup_playwright():
        print("Не удалось настроить Playwright. Приложение может работать некорректно.")

    app = QApplication(sys.argv)
    app.setStyle("Fusion")

    app.setStyleSheet("""
        QWidget {
            background-color: #1E1E1E;
            color: #DDDDDD;
        }
        QToolTip {
            background-color: #3A3A3A;
            color: #DDDDDD;
            border: 1px solid #555555;
            border-radius: 4px;
            padding: 5px;
        }
    """)

    window = CryptoApp()
    window.show()
    sys.exit(app.exec_())
