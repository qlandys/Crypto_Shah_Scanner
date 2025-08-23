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
from PyQt5.QtWidgets import QCompleter, QTabWidget, QInputDialog, QSizePolicy
from PyQt5.QtCore import Qt, QThread, pyqtSignal, QPoint, QPropertyAnimation, QEvent, QSize, QSettings, QEasingCurve, QTimer
from PyQt5.QtGui import (QIcon, QFont, QPalette, QColor, QStandardItemModel,
                         QStandardItem, QKeySequence, QPainter, QPixmap,
                         QLinearGradient, QBrush, QPen)
from database import Database, Coin
from parser import TradingViewParser
import multiprocessing
from parser import parse_coin_in_process, parse_coins_batch_process
import io
from clicker_window import ClickerWindow
from datetime import datetime, timedelta
import concurrent.futures

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')


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


# Установка обработчика ошибок
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
                subprocess.run(
                    [sys.executable, "-m", "playwright", "install", "chromium"],
                    check=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    creationflags=subprocess.CREATE_NO_WINDOW
                )
            except subprocess.CalledProcessError as e:
                print(f"Ошибка установки браузеров: {e.stderr.decode()}")
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
            opacity: 0;
        """)
        self.setFixedHeight(20)
        self.animation = QPropertyAnimation(self, b"opacity")
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

    def show_notification(self, button):
        self.setText("✓ Скопировано")
        global_pos = button.mapToGlobal(QPoint(0, 0))
        parent_pos = self.parent().mapFromGlobal(global_pos)
        self.move(parent_pos.x() - 15, parent_pos.y() + button.height() + 5)
        self.show()
        self.raise_()
        self.animation.start()


class ExchangeFilterWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.layout = QHBoxLayout(self)
        self.layout.setContentsMargins(0, 0, 0, 0)

        # Текстовое поле для отображения выбранных бирж
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

        # Диалог выбора бирж
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

        # Поле поиска
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Поиск бирж...")
        self.search_input.setStyleSheet("font-size: 13px;")
        self.dialog_layout.addWidget(self.search_input)

        # Список бирж с чекбоксами
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
        self.list_widget.itemClicked.connect(self.toggle_item_check)
        self.dialog_layout.addWidget(self.list_widget, 1)

        # Кнопки управления
        btn_layout = QHBoxLayout()
        self.select_all_btn = QPushButton("Выбрать все")
        self.select_all_btn.clicked.connect(self.select_all)
        self.deselect_all_btn = QPushButton("Снять все")
        self.deselect_all_btn.clicked.connect(self.deselect_all)
        btn_layout.addWidget(self.select_all_btn)
        btn_layout.addWidget(self.deselect_all_btn)
        self.dialog_layout.addLayout(btn_layout)

        # Кнопки подтверждения
        button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        button_box.setStyleSheet("background-color: transparent;")
        button_box.accepted.connect(self.accept_selection)
        button_box.rejected.connect(self.dialog.reject)
        self.dialog_layout.addWidget(button_box)

        self.search_input.textChanged.connect(self.filter_items)
        self.selected_exchanges = set()
        self.all_exchanges = []

    def toggle_item_check(self, item):
        if item.checkState() == Qt.Checked:
            item.setCheckState(Qt.Unchecked)
        else:
            item.setCheckState(Qt.Checked)

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
            # Создаем парсер с уникальным ID
            self.parser = TradingViewParser(headless=True, instance_id=self.thread_id)
            data_tuple = self.parser.parse_coin(self.coin_name)
            # Извлекаем только результат из tuple (coin_name, result)
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

    def cancel(self):
        self._is_cancelled = True

    def run(self):
        total = len(self.coin_names)
        self.start_time = time.time()

        # Разбиваем монеты на батчи для каждого воркера
        chunk_size = max(1, len(self.coin_names) // self.max_workers)
        chunks = [self.coin_names[i:i + chunk_size] for i in range(0, len(self.coin_names), chunk_size)]

        with concurrent.futures.ProcessPoolExecutor(max_workers=self.max_workers) as executor:
            # Запускаем процессы для обработки каждого батча
            future_to_chunk = {
                executor.submit(parse_coins_batch_process, chunk, True): chunk
                for chunk in chunks
            }

            processed = 0
            for future in concurrent.futures.as_completed(future_to_chunk):
                if self._is_cancelled:
                    break

                chunk = future_to_chunk[future]
                try:
                    chunk_results = future.result()

                    for coin_name, result in chunk_results.items():
                        processed += 1

                        # Расчет оставшегося времени
                        elapsed = time.time() - self.start_time
                        time_per_coin = elapsed / processed
                        remaining_seconds = time_per_coin * (total - processed)

                        # Форматирование времени в ЧЧ:ММ:СС
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
                    # Если весь батч упал с ошибкой
                    for coin_name in chunk:
                        processed += 1
                        self.error.emit(str(e), coin_name)
                        self.progress.emit(processed, total, coin_name, "Ошибка батча")

        self.finished.emit()


# Добавьте методы для очистки памяти в класс ProfileTab
def start_memory_cleanup(self):
    """Запускает периодическую очистку памяти"""
    self.cleanup_timer = QTimer(self)
    self.cleanup_timer.timeout.connect(self.memory_cleanup)
    self.cleanup_timer.start(30000)  # Каждые 30 секунд


def stop_memory_cleanup(self):
    """Останавливает очистку памяти"""
    if hasattr(self, 'cleanup_timer'):
        self.cleanup_timer.stop()
        self.cleanup_timer.deleteLater()


def memory_cleanup(self):
    """Очистка памяти во время пакетной обработки"""
    if hasattr(self, 'batch_thread') and self.batch_thread.isRunning():
        # Принудительный сбор мусора
        import gc
        gc.collect()


# Обновите метод load_file в классе ProfileTab
def load_file(self):
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

        self.scan_btn.setEnabled(False)
        self.load_file_btn.setEnabled(False)
        self.progress_bar.setVisible(False)
        self.batch_progress_bar.setVisible(True)
        self.batch_progress_bar.setRange(0, len(coin_names))
        self.batch_progress_bar.setValue(0)
        self.batch_progress_bar.setFormat("Подготовка к сканированию...")
        self.cancel_btn.setVisible(True)

        # Определяем оптимальное количество процессов
        coin_count = len(coin_names)
        max_workers = min(8, max(2, coin_count // 10))  # 1 воркер на каждые 10 монет, но не более 8

        # Создаем уникальный ID для этого потока пакетного сканирования
        thread_id = f"batch_{int(time.time())}_{id(self)}"
        self.batch_thread = BatchParseThread(coin_names, self.db, thread_id, max_workers)
        self.batch_thread.progress.connect(self.on_batch_progress)
        self.batch_thread.finished.connect(self.on_batch_finished)
        self.batch_thread.error.connect(self.on_batch_error)
        self.batch_thread.start()

        # Запускаем очистку памяти во время пакетной обработки
        self.start_memory_cleanup()

    except Exception as e:
        QMessageBox.critical(self, "Ошибка", f"Не удалось загрузить файл: {str(e)}")
        self.scan_btn.setEnabled(True)
        self.load_file_btn.setEnabled(True)
        self.stop_memory_cleanup()


class ProfileTab(QWidget):
    def __init__(self, profile_name, parent=None):
        super().__init__(parent)
        self.profile_name = profile_name
        self.db = None  # Явно инициализируем как None
        self.copy_notification = CopyNotification(self)
        self.copy_notification.hide()

        try:
            self.db = Database(profile_name)
        except Exception as e:
            QMessageBox.warning(self, "Ошибка", f"Не удалось загрузить базу данных: {str(e)}")
            # Создаем новую базу данных при ошибке
            self.db = Database(profile_name)
            self.db.save()  # Создаем пустой файл

        self.init_ui()
        self.apply_theme()
        self.update_exchange_list()
        self.reset_filters()

    def closeEvent(self, event):
        if hasattr(self, 'scan_thread') and self.scan_thread.isRunning():
            try:
                self.scan_thread.terminate()
                self.scan_thread.wait(1000)
            except:
                pass

        if hasattr(self, 'batch_thread') and self.batch_thread.isRunning():
            try:
                self.batch_thread.cancel()
                self.batch_thread.terminate()
                self.batch_thread.wait(1000)
            except:
                pass

        cleanup_threads.cleanup_threads()
        event.accept()

    def start_memory_cleanup(self):
        """Запускает периодическую очистку памяти"""
        self.cleanup_timer = QTimer()
        self.cleanup_timer.timeout.connect(self.memory_cleanup)
        self.cleanup_timer.start(30000)  # Каждые 30 секунд

    def stop_memory_cleanup(self):
        """Останавливает очистку памяти"""
        if hasattr(self, 'cleanup_timer'):
            self.cleanup_timer.stop()
            self.cleanup_timer.deleteLater()

    def memory_cleanup(self):
        """Очистка памяти во время пакетной обработки"""
        if hasattr(self, 'batch_thread') and self.batch_thread.isRunning():
            # Принудительный сбор мусора
            import gc
            gc.collect()

            # Также пытаемся освободить неиспользуемую память
            try:
                import ctypes
                ctypes.CDLL('libc.so.6').malloc_trim(0)
            except:
                pass  # Не критично, если не сработает

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
        # Основной layout
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(15, 15, 15, 15)
        main_layout.setSpacing(15)

        # Группа сканирования
        scan_group = QGroupBox("Сканирование монеты")
        scan_layout = QVBoxLayout(scan_group)
        scan_layout.setSpacing(15)

        # Верхняя строка с полем ввода и кнопками
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

        # Прогресс-бары
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

        # Результаты сканирования
        results_layout = QVBoxLayout()
        results_layout.setSpacing(8)

        # Название монеты с кнопкой копирования
        name_layout = QHBoxLayout()
        name_layout.setContentsMargins(0, 0, 0, 0)
        name_layout.setSpacing(5)  # Уменьшаем отступ между элементами

        self.coin_name_label = QLabel("Название:")
        self.coin_name_label.setFont(QFont("Arial", 11, QFont.Bold))
        self.coin_name_value = QLabel("")
        self.coin_name_value.setFont(QFont("Arial", 11, QFont.Bold))
        self.coin_name_value.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Preferred)  # Не растягивать по горизонтали

        # Используем иконку для кнопки копирования
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
        self.copy_btn.setVisible(False)  # Скрываем кнопку до сканирования

        name_layout.addWidget(self.coin_name_label)
        name_layout.addWidget(self.coin_name_value)
        name_layout.addSpacing(5)  # Добавляем небольшой отступ
        name_layout.addWidget(self.copy_btn)
        name_layout.addStretch()  # Добавляем растягивающий элемент

        results_layout.addLayout(name_layout)

        # Спотовые биржи
        spot_layout = QHBoxLayout()
        spot_label = QLabel("Спотовые биржи:")
        spot_label.setFont(QFont("Arial", 10))
        self.spot_value = QLabel("")
        self.spot_value.setFont(QFont("Arial", 10))
        self.spot_value.setWordWrap(True)
        spot_layout.addWidget(spot_label)
        spot_layout.addWidget(self.spot_value, 1)
        results_layout.addLayout(spot_layout)

        # Фьючерсные биржи
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

        # Группа поиска
        search_group = QGroupBox("Поиск по базе данных")
        search_layout = QVBoxLayout(search_group)
        search_layout.setSpacing(15)

        # Фильтры
        filter_layout = QGridLayout()
        filter_layout.setColumnStretch(1, 1)
        filter_layout.setColumnStretch(3, 1)
        filter_layout.setHorizontalSpacing(10)
        filter_layout.setVerticalSpacing(10)

        # Поиск по названию
        filter_layout.addWidget(QLabel("Поиск по названию:"), 0, 0)
        self.coin_search_input = QLineEdit()
        self.coin_search_input.setPlaceholderText("Введите название монеты")
        self.coin_search_input.setMinimumHeight(36)
        self.coin_search_input.returnPressed.connect(self.apply_filter)
        filter_layout.addWidget(self.coin_search_input, 0, 1, 1, 4)

        # Фильтр по биржам
        filter_layout.addWidget(QLabel("Выберите биржи:"), 1, 0)
        self.exchange_filter = ExchangeFilterWidget()
        filter_layout.addWidget(self.exchange_filter, 1, 1, 1, 4)

        # Дополнительные фильтры
        filter_layout.addWidget(QLabel("Тип торговли:"), 2, 0)
        self.trade_type = QComboBox()
        self.trade_type.addItems(["Все", "Только спот", "Только фьючерсы"])
        self.trade_type.setMinimumHeight(36)
        filter_layout.addWidget(self.trade_type, 2, 1)

        self.exclusive_check = QCheckBox("Только на выбранных биржах")
        self.exclusive_check.setToolTip("Показывать только монеты, которые есть ТОЛЬКО на выбранных биржах")
        filter_layout.addWidget(self.exclusive_check, 2, 2, 1, 2)

        # Кнопки управления
        search_btn = QPushButton("Найти")
        search_btn.setMinimumHeight(36)
        search_btn.clicked.connect(self.apply_filter)
        filter_layout.addWidget(search_btn, 2, 4)

        reset_btn = QPushButton("Сбросить фильтры")
        reset_btn.setMinimumHeight(36)
        reset_btn.clicked.connect(self.reset_filters)
        filter_layout.addWidget(reset_btn, 2, 5)

        search_layout.addLayout(filter_layout)

        # Таблица результатов
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["Монета", "Спотовые биржи", "Фьючерсные биржи"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.table.setMinimumHeight(400)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)

        # Фиксируем заголовки при скролле
        self.table.verticalHeader().setSectionResizeMode(QHeaderView.Fixed)
        self.table.verticalHeader().setDefaultSectionSize(40)
        self.table.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.table.setHorizontalScrollMode(QAbstractItemView.ScrollPerPixel)

        search_layout.addWidget(self.table, 1)
        main_layout.addWidget(search_group, 1)

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
            # Сбрасываем предыдущий парсер, если он есть (для исправления бага с повторным запуском)
            if hasattr(self, 'scan_thread') and hasattr(self.scan_thread, 'parser'):
                try:
                    self.scan_thread.parser.reset()
                except:
                    pass

            coin_name = self.coin_input.text().strip().upper()
            if not coin_name:
                QMessageBox.warning(self, "Ошибка", "Введите название монеты")
                return
            if not re.match(r"^[A-Z0-9]{2,10}$", coin_name):
                QMessageBox.warning(self, "Ошибка", "Некорректное название монеты")
                return

            # Скрываем кнопку копирования перед началом сканирования
            self.copy_btn.setVisible(False)

            self.scan_btn.setEnabled(False)
            self.load_file_btn.setEnabled(False)
            self.coin_name_value.setText("")
            self.spot_value.setText("")
            self.futures_value.setText("")
            self.progress_bar.setVisible(True)
            self.batch_progress_bar.setVisible(False)

            # Создаем уникальный ID для этого потока сканирования
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
        # Сбрасываем предыдущий парсер, если он есть (для исправления бага с повторным запуском)
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
            self.batch_progress_bar.setFormat("Подготовка к сканированию...")
            self.cancel_btn.setVisible(True)

            # Определяем оптимальное количество процессов
            coin_count = len(coin_names)
            max_workers = min(5, max(2, coin_count // 20))  # 1 воркер на каждые 20 монет, но не более 5

            # Создаем уникальный ID для этого потока пакетного сканирования
            thread_id = f"batch_{int(time.time())}_{id(self)}"
            self.batch_thread = BatchParseThread(coin_names, self.db, thread_id, max_workers)
            self.batch_thread.progress.connect(self.on_batch_progress)
            self.batch_thread.finished.connect(self.on_batch_finished)
            self.batch_thread.error.connect(self.on_batch_error)
            self.batch_thread.start()

            # Запускаем очистку памяти во время пакетной обработки
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

            # Показываем кнопку копирования только после успешного сканирования
            self.copy_btn.setVisible(True)

            spot_str = ", ".join(data['spot'])
            futures_str = ", ".join(data['futures'])

            # Проверяем, что база данных инициализирована
            if hasattr(self, 'db') and self.db is not None:
                self.db.save_coin(data['name'], spot_str, futures_str)
                self.db.reload_from_file()
                self.update_exchange_list()

                # НЕМЕДЛЕННО обновляем таблицу с новыми данными
                self.reset_filters()

                QMessageBox.information(self, "Успех", "Данные сохранены в базу данных!")
            else:
                # Переинициализируем базу данных при необходимости
                self.db = Database(self.profile_name)
                self.db.save_coin(data['name'], spot_str, futures_str)
                self.db.reload_from_file()
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
        # Скрываем кнопку копирования при ошибке
        self.copy_btn.setVisible(False)
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

        # Останавливаем очистку памяти
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
            # Останавливаем очистку памяти при отмене
            self.stop_memory_cleanup()

    def apply_filter(self):
        coin_name = self.coin_search_input.text().strip().upper()
        trade_type_text = self.trade_type.currentText()
        exclusive_mode = self.exclusive_check.isChecked()

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
                coin_spot_exchanges = [e.strip() for e in coin.spot_exchanges.split(',')]

            coin_futures_exchanges = []
            if coin.futures_exchanges:
                coin_futures_exchanges = [e.strip() for e in coin.futures_exchanges.split(',')]

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

            if trade_type == "spot":
                if not coin_spot_exchanges or coin_futures_exchanges:
                    continue
            elif trade_type == "futures":
                if not coin_futures_exchanges or coin_spot_exchanges:
                    continue

            filtered_results.append(coin)

        filtered_results.sort(key=lambda x: x.name)

        self.table.setRowCount(len(filtered_results))
        for row_idx, coin in enumerate(filtered_results):
            # Создаем виджет для ячейки с названием монеты и кнопкой копирования
            coin_widget = QWidget()
            coin_layout = QHBoxLayout(coin_widget)
            coin_layout.setContentsMargins(8, 0, 8, 0)
            coin_layout.setSpacing(5)  # Увеличиваем отступ между элементами

            # Название монеты
            coin_label = QLabel(coin.name)
            coin_label.setFont(QFont("Arial", 10, QFont.Bold))
            coin_label.setStyleSheet("background-color: transparent;")
            coin_label.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Preferred)

            # Кнопка копирования (только если есть название монеты)
            if coin.name:
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

                coin_layout.addWidget(coin_label)
                # Добавляем отступ перед кнопкой
                coin_layout.addSpacing(8)
                coin_layout.addWidget(copy_btn)
                coin_layout.addStretch()
            else:
                coin_layout.addWidget(coin_label)

            self.table.setCellWidget(row_idx, 0, coin_widget)

            # Колонка со спотовыми биржами
            spot_item = QTableWidgetItem(coin.spot_exchanges or "")
            spot_item.setToolTip(coin.spot_exchanges)
            self.table.setItem(row_idx, 1, spot_item)

            # Колонка с фьючерсными биржами
            futures_item = QTableWidgetItem(coin.futures_exchanges or "")
            futures_item.setToolTip(coin.futures_exchanges)
            self.table.setItem(row_idx, 2, futures_item)

    def reset_filters(self):
        self.coin_search_input.clear()
        self.trade_type.setCurrentIndex(0)
        self.exclusive_check.setChecked(False)
        self.exchange_filter.set_exchanges(self.get_unique_exchanges())
        self.apply_filter()

    def copy_coin_name(self, button):
        coin_name = self.coin_name_value.text()
        if coin_name:
            pyperclip.copy(f"{coin_name}USDT")
            self.copy_notification.show_notification(button)

    def copy_coin_name_from_table(self, name):
        pyperclip.copy(f"{name}USDT")
        # Находим кнопку, которая вызвала это действие
        for i in range(self.table.rowCount()):
            widget = self.table.cellWidget(i, 0)
            if widget:
                copy_btn = widget.findChild(QPushButton)
                if copy_btn and copy_btn == self.sender():
                    self.copy_notification.show_notification(copy_btn)
                    break


CLICKER_OPENED = False


class CryptoApp(QMainWindow):
    def __init__(self):
        super().__init__()
        # Инициализация атрибутов для переименования вкладок
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
        # Увеличиваем минимальный размер окна для лучшего отображения данных
        self.setMinimumSize(1000, 900)

        central_widget = QWidget()
        central_widget.setObjectName("central_widget")
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # Верхняя панель
        header = QWidget()
        header.setFixedHeight(50)
        header.setStyleSheet("background-color: #333333;")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(20, 0, 20, 0)

        # Название приложения
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

        # Центральное пространство
        header_layout.addStretch()

        # Кнопки управления профилями
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(10)

        # Кнопка "+" для создания новой вкладки (как в браузере)
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
        header_layout.addLayout(btn_layout)

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

        btn_layout.addWidget(self.copy_profile_btn)
        btn_layout.addWidget(self.delete_profile_btn)
        header_layout.addLayout(btn_layout)

        # Кнопка закрепления с иконкой
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

        main_layout.addWidget(header)

        # Основная область с вкладками
        self.tab_widget = QTabWidget()
        self.tab_widget.setTabsClosable(True)
        self.tab_widget.tabCloseRequested.connect(self.close_tab)
        self.tab_widget.setMovable(True)

        # Настраиваем иконку закрытия вкладок
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

        # Обработка двойного клика для переименования вкладки
        self.tab_widget.tabBar().installEventFilter(self)

        # Устанавливаем фильтр событий для всего приложения
        QApplication.instance().installEventFilter(self)

        main_layout.addWidget(self.tab_widget, 1)

    def open_freak_parser(self):
        # Проверяем, не открыт ли уже парсер и существует ли окно
        if hasattr(self, 'freak_parser_window') and self.freak_parser_window is not None:
            try:
                if self.freak_parser_window.isVisible():
                    self.freak_parser_window.raise_()
                    self.freak_parser_window.activateWindow()
                    return
                else:
                    # Окно существует, но не видимо (возможно, закрыто) - удаляем ссылку
                    self.freak_parser_window = None
            except:
                # Если произошла ошибка при проверке окна (например, оно было закрыто)
                self.freak_parser_window = None

        # Если окно не открыто, создаем новое
        if not hasattr(self, 'freak_parser_window') or self.freak_parser_window is None:
            try:
                from freak_parser import TradingViewParserGUI
                self.freak_parser_window = TradingViewParserGUI()
                # Подключаем сигнал на закрытие окна, чтобы обнулить ссылку
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

        # Подключаем сигнал на закрытие окна кликера
        self.clicker_window.destroyed.connect(self.on_clicker_closed)

    def on_clicker_closed(self):
        global CLICKER_OPENED
        CLICKER_OPENED = False

    def show_new_tab_menu(self):
        """Показывает меню для создания новой вкладки"""
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

        # Пункт для создания нового профиля
        new_action = menu.addAction("➕ Создать новый профиль")
        new_action.triggered.connect(self.create_new_profile)

        menu.addSeparator()

        # Пункты для открытия существующих профилей
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
        """Открывает профиль в новой вкладке"""
        # Проверяем, не открыт ли уже этот профиль
        for i in range(self.tab_widget.count()):
            if self.tab_widget.tabText(i) == profile_name:
                self.tab_widget.setCurrentIndex(i)
                return

        # Если не открыт, создаем новую вкладку
        self.add_profile_tab(profile_name)

    def eventFilter(self, source, event):
        # Обработка двойного клика для переименования вкладки
        if (event.type() == QEvent.MouseButtonDblClick and
                source is self.tab_widget.tabBar()):
            index = source.tabAt(event.pos())
            if index >= 0:
                self.start_rename_tab(index)
                return True

        # Обработка клика вне поля редактирования для завершения переименования
        if (self.is_renaming and event.type() == QEvent.MouseButtonPress and
                source is not self.rename_edit):
            self.finish_rename_tab()
            return True

        # Обработка потери фокуса при переименовании
        if (self.is_renaming and source is self.rename_edit and
                event.type() == QEvent.FocusOut):
            self.finish_rename_tab()
            return True

        # Обработка нажатия Esc для отмены переименования
        if (self.is_renaming and event.type() == QEvent.KeyPress and
                event.key() == Qt.Key_Escape):
            self.cancel_rename_tab()
            return True

        return super().eventFilter(source, event)

    def start_rename_tab(self, index):
        # Закрываем предыдущее поле редактирования, если оно есть
        if self.rename_edit:
            self.finish_rename_tab()

        # Начинаем переименование вкладки
        self.renaming_tab_index = index
        self.is_renaming = True
        old_name = self.tab_widget.tabText(index)

        # Создаем поле редактирования
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

        # Заменяем вкладку на поле редактирования
        self.tab_widget.tabBar().setTabButton(index, QTabBar.LeftSide, None)
        self.tab_widget.tabBar().setTabButton(index, QTabBar.RightSide, None)
        self.tab_widget.tabBar().setTabText(index, "")

        # Размещаем поле редактирования на вкладке
        tab_rect = self.tab_widget.tabBar().tabRect(index)
        self.rename_edit.setParent(self.tab_widget.tabBar())
        self.rename_edit.setGeometry(tab_rect)
        self.rename_edit.show()
        self.rename_edit.setFocus()

    def finish_rename_tab(self):
        if self.renaming_tab_index >= 0 and self.rename_edit:
            new_name = self.rename_edit.text().strip()
            old_name = self.tab_widget.tabText(self.renaming_tab_index)

            # Если имя изменилось, применяем изменения
            if new_name and new_name != old_name:
                # Проверяем уникальность имени
                unique = True
                for i in range(self.tab_widget.count()):
                    if i != self.renaming_tab_index and self.tab_widget.tabText(i) == new_name:
                        unique = False
                        break

                if unique:
                    # Переименовываем вкладку
                    self.tab_widget.setTabText(self.renaming_tab_index, new_name)

                    # Переименовываем файл базы данных
                    try:
                        tab = self.tab_widget.widget(self.renaming_tab_index)
                        if hasattr(tab, 'db'):
                            # Переименовываем файл БД
                            old_db_path = tab.db.filename
                            new_db_path = os.path.join(os.path.dirname(old_db_path), f"{new_name}.json")

                            # Переименовываем файл
                            if os.path.exists(old_db_path):
                                os.rename(old_db_path, new_db_path)

                            # Обновляем путь к файлу в объекте БД
                            tab.db.filename = new_db_path
                            tab.db.profile_name = new_name
                            tab.profile_name = new_name
                    except Exception as e:
                        QMessageBox.warning(self, "Ошибка", f"Не удалось переименовать профиль: {str(e)}")
                        # Восстанавливаем старое имя в случае ошибки
                        self.tab_widget.setTabText(self.renaming_tab_index, old_name)

            # Восстанавливаем обычный вид вкладки
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
        """Отмена переименования вкладки"""
        if self.renaming_tab_index >= 0:
            # Восстанавливаем исходное имя
            old_name = self.tab_widget.tabText(self.renaming_tab_index)
            self.tab_widget.setTabText(self.renaming_tab_index, old_name)

            # Восстанавливаем обычный вид вкладки
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
        """Восстанавливает кнопки закрытия для вкладки"""
        # В QTabBar кнопки закрытия создаются автоматически при установке setTabsClosable(True)
        # Просто обновляем вкладку, чтобы восстановить кнопки
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
        # Проверяем, что профиль еще не открыт
        for i in range(self.tab_widget.count()):
            if self.tab_widget.tabText(i) == profile_name:
                self.tab_widget.setCurrentIndex(i)
                return  # Профиль уже открыт

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

        # Проверяем уникальность имени
        for i in range(self.tab_widget.count()):
            if self.tab_widget.tabText(i) == name:
                QMessageBox.warning(self, "Ошибка", "Профиль с таким именем уже открыт!")
                return

        db = Database(name)
        db.save()  # Создаем пустой файл
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

        # Проверяем уникальность имени
        for i in range(self.tab_widget.count()):
            if self.tab_widget.tabText(i) == new_name:
                QMessageBox.warning(self, "Ошибка", "Профиль с таким именем уже открыт!")
                return

        # Копируем БД
        current_db = Database(current_name)
        new_db = current_db.copy_profile(new_name)

        # Добавляем новую вкладку
        self.add_profile_tab(new_name)

    def delete_current_profile(self):
        current_index = self.tab_widget.currentIndex()
        if current_index < 0:
            return

        if self.tab_widget.count() <= 1:
            QMessageBox.warning(self, "Ошибка", "Нельзя удалить последний профиль!")
            return

        profile_name = self.tab_widget.tabText(current_index)

        # Добавляем диалог подтверждения удаления
        reply = QMessageBox.question(
            self,
            "Подтверждение удаления",
            f"Вы уверены, что хотите удалить профиль '{profile_name}'? Это действие нельзя отменить.",
            QMessageBox.Yes | QMessageBox.No
        )

        if reply == QMessageBox.No:
            return

        # Удаляем файл базы данных
        try:
            db = Database(profile_name)
            db.delete_profile()
        except Exception as e:
            QMessageBox.warning(self, "Ошибка", f"Не удалось удалить файл профиля: {str(e)}")

        # Закрываем вкладку
        widget = self.tab_widget.widget(current_index)
        widget.deleteLater()
        self.tab_widget.removeTab(current_index)

    def close_tab(self, index):
        # Просто закрываем вкладку без диалога подтверждения
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

    # Устанавливаем темную тему для всего приложения
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
