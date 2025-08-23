import asyncio
import sys
import os
from PyQt5.QtWidgets import (QApplication, QMainWindow, QPushButton,
                             QVBoxLayout, QWidget, QLabel, QLineEdit,
                             QListWidget, QListWidgetItem, QCheckBox,
                             QHBoxLayout, QMessageBox, QGroupBox, QDialog)
from PyQt5.QtCore import Qt, QTimer, QPropertyAnimation, QEasingCurve, QThread, pyqtSignal
from PyQt5.QtGui import QFont, QIcon, QColor
from playwright.async_api import async_playwright


class ExchangeListWidget(QListWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.exchanges = [
            "Binance", "Binance.US", "BingX", "Bitazza", "Bitfinex", "bitFlyer",
            "BitGet", "Bithumb", "Bitkub", "BitMart", "BitMEX", "Bitrue", "Bitso",
            "Bitstamp", "Bitvavo", "BTSE", "ByBit", "Coinbase", "CoinEx", "CoinW",
            "Crypto.com", "Deepcoin", "Delta Exchange", "Delta Exchange India",
            "Deribit", "Gate.io", "Gemini", "HTX", "KCEX", "Kraken", "KuCoin",
            "LBANK", "MEXC", "OKX", "PHEMEX", "Pionex", "Poloniex", "Tokenize",
            "Toobit", "UpBit", "WEEX", "WhiteBIT", "WOO X", "Zoomex"
        ]
        self.setup_ui()

    def setup_ui(self):
        self.setSelectionMode(QListWidget.MultiSelection)
        for exchange in self.exchanges:
            item = QListWidgetItem(self)
            checkbox = QCheckBox(exchange)
            checkbox.setStyleSheet("""
                QCheckBox {
                    color: #DDDDDD;
                    background-color: transparent;
                    font-size: 13px;
                    padding: 5px;
                    spacing: 8px;
                }
                QCheckBox::indicator {
                    width: 18px;
                    height: 18px;
                    border: 2px solid #555555;
                    border-radius: 4px;
                    background-color: #3A3A3A;
                }
                QCheckBox::indicator:checked {
                    border: 2px solid #6A5AF9;
                    background-color: #6A5AF9;
                }
                QCheckBox::indicator:unchecked:hover {
                    border: 2px solid #777777;
                }
                QCheckBox::indicator:checked:hover {
                    border: 2px solid #5B4AE9;
                    background-color: #5B4AE9;
                }
            """)
            checkbox.setChecked(False)
            self.setItemWidget(item, checkbox)

    def get_selected_exchanges(self):
        selected = []
        for i in range(self.count()):
            item = self.item(i)
            widget = self.itemWidget(item)
            if widget.isChecked():
                selected.append(widget.text())
        return selected

    def select_all(self):
        for i in range(self.count()):
            item = self.item(i)
            widget = self.itemWidget(item)
            widget.setChecked(True)

    def deselect_all(self):
        for i in range(self.count()):
            item = self.item(i)
            widget = self.itemWidget(item)
            widget.setChecked(False)

    def filter_items(self, text):
        for i in range(self.count()):
            item = self.item(i)
            widget = self.itemWidget(item)
            if text.lower() in widget.text().lower():
                item.setHidden(False)
            else:
                item.setHidden(True)


class InstrumentTypeWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setup_ui()

    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        group = QGroupBox("Тип инструмента")
        group.setStyleSheet("""
            QGroupBox {
                background-color: #2D2D2D;
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
        """)
        group_layout = QVBoxLayout(group)

        self.spot_checkbox = QCheckBox("Спот")
        self.futures_checkbox = QCheckBox("Фьючерсы")
        self.perpetual_checkbox = QCheckBox("Бессрочные контракты")

        # Стили для чекбоксов
        checkbox_style = """
            QCheckBox {
                color: #DDDDDD;
                background-color: transparent;
                font-size: 12px;
                padding: 5px;
            }
            QCheckBox::indicator {
                width: 16px;
                height: 16px;
            }
            QCheckBox::indicator:unchecked {
                border: 1px solid #555555;
                background-color: #3A3A3A;
                border-radius: 3px;
            }
            QCheckBox::indicator:checked {
                border: 1px solid #6A5AF9;
                background-color: #6A5AF9;
                border-radius: 3px;
            }
        """

        self.spot_checkbox.setStyleSheet(checkbox_style)
        self.futures_checkbox.setStyleSheet(checkbox_style)
        self.perpetual_checkbox.setStyleSheet(checkbox_style)

        group_layout.addWidget(self.spot_checkbox)
        group_layout.addWidget(self.futures_checkbox)
        group_layout.addWidget(self.perpetual_checkbox)

        buttons_layout = QHBoxLayout()
        self.select_all_btn = QPushButton("Выбрать все")
        self.select_all_btn.setStyleSheet("""
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
        self.select_all_btn.clicked.connect(self.select_all)
        buttons_layout.addWidget(self.select_all_btn)

        self.deselect_all_btn = QPushButton("Снять все")
        self.deselect_all_btn.setStyleSheet("""
            QPushButton {
                background-color: #444444;
                color: #DDDDDD;
                border: none;
                padding: 8px 15px;
                border-radius: 4px;
                font-weight: normal;
                font-size: 12px;
            }
            QPushButton:hover {
                background-color: #555555;
            }
        """)
        self.deselect_all_btn.clicked.connect(self.deselect_all)
        buttons_layout.addWidget(self.deselect_all_btn)

        group_layout.addLayout(buttons_layout)
        layout.addWidget(group)

    def get_selected_types(self):
        selected = []
        if self.spot_checkbox.isChecked():
            selected.append("Спот")
        if self.futures_checkbox.isChecked():
            selected.append("Фьючерсы")
        if self.perpetual_checkbox.isChecked():
            selected.append("Бессрочные контракты")
        return selected

    def select_all(self):
        self.spot_checkbox.setChecked(True)
        self.futures_checkbox.setChecked(True)
        self.perpetual_checkbox.setChecked(True)

    def deselect_all(self):
        self.spot_checkbox.setChecked(False)
        self.futures_checkbox.setChecked(False)
        self.perpetual_checkbox.setChecked(False)


class ParserThread(QThread):
    progress_signal = pyqtSignal(str)
    finished_signal = pyqtSignal()
    error_signal = pyqtSignal(str)

    def __init__(self, exchange_names, instrument_types, filename):
        super().__init__()
        self.exchange_names = exchange_names
        self.instrument_types = instrument_types
        self.filename = filename

    def run(self):
        try:
            # Создаем новый event loop для этого потока
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

            # Запускаем парсинг
            loop.run_until_complete(tradingview_parser(
                self.exchange_names,
                self.instrument_types,
                self.filename,
                self.progress_signal.emit
            ))

            self.finished_signal.emit()
        except Exception as e:
            self.error_signal.emit(str(e))


class TradingViewParserGUI(QDialog):
    finished = pyqtSignal()

    def __init__(self):
        super().__init__()
        self.setWindowTitle("TradingView Parser")
        self.setGeometry(100, 100, 900, 900)
        self.is_parsing = False
        self.apply_dark_theme()

        # Создаем основной layout
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(15)

        # Заголовок
        title_label = QLabel("Настройки парсера TradingView")
        title_label.setAlignment(Qt.AlignCenter)
        title_label.setStyleSheet("font-size: 18px; font-weight: bold; color: #DDDDDD;")
        layout.addWidget(title_label)

        # Поле для названия файла
        filename_layout = QHBoxLayout()
        filename_label = QLabel("Название TXT файла:")
        filename_label.setStyleSheet("color: #DDDDDD;")
        filename_layout.addWidget(filename_label)

        self.filename_input = QLineEdit()
        self.filename_input.setPlaceholderText("Введите название файла...")
        self.filename_input.setText("tickers")
        self.filename_input.setStyleSheet("""
            QLineEdit {
                background-color: #3A3A3A;
                color: #DDDDDD;
                border: 1px solid #555555;
                border-radius: 4px;
                padding: 8px 12px;
                font-size: 13px;
            }
        """)
        filename_layout.addWidget(self.filename_input)
        layout.addLayout(filename_layout)

        # Тип инструмента
        self.instrument_type_widget = InstrumentTypeWidget()
        layout.addWidget(self.instrument_type_widget)

        # Поиск бирж
        search_layout = QHBoxLayout()
        search_label = QLabel("Поиск бирж:")
        search_label.setStyleSheet("color: #DDDDDD;")
        search_layout.addWidget(search_label)

        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Введите название биржи...")
        self.search_input.setStyleSheet("""
            QLineEdit {
                background-color: #3A3A3A;
                color: #DDDDDD;
                border: 1px solid #555555;
                border-radius: 4px;
                padding: 8px 12px;
                font-size: 13px;
            }
        """)
        self.search_input.textChanged.connect(self.filter_exchanges)
        search_layout.addWidget(self.search_input)
        layout.addLayout(search_layout)

        # Список бирж с чекбоксами
        layout.addWidget(QLabel("Выберите биржи:"))
        self.exchange_list = ExchangeListWidget()
        self.exchange_list.setStyleSheet("""
            QListWidget {
                background-color: #3A3A3A;
                color: #DDDDDD;
                border: 1px solid #555555;
                border-radius: 4px;
                font-size: 13px;
            }
            QListWidget::item {
                padding: 8px 12px;
                border-bottom: 1px solid #444444;
                height: 30px;
            }
            QListWidget::item:hover {
                background-color: #4A4A4A;
            }
        """)
        self.exchange_list.itemClicked.connect(self.on_exchange_item_clicked)
        layout.addWidget(self.exchange_list)

        # Кнопки выбора всех/снятия всех для бирж
        buttons_layout = QHBoxLayout()
        self.select_all_btn = QPushButton("Выбрать все")
        self.select_all_btn.setStyleSheet("""
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
        self.select_all_btn.clicked.connect(self.exchange_list.select_all)
        buttons_layout.addWidget(self.select_all_btn)

        self.deselect_all_btn = QPushButton("Снять все")
        self.deselect_all_btn.setStyleSheet("""
            QPushButton {
                background-color: #444444;
                color: #DDDDDD;
                border: none;
                padding: 8px 15px;
                border-radius: 4px;
                font-weight: normal;
                font-size: 12px;
            }
            QPushButton:hover {
                background-color: #555555;
            }
        """)
        self.deselect_all_btn.clicked.connect(self.exchange_list.deselect_all)
        buttons_layout.addWidget(self.deselect_all_btn)
        layout.addLayout(buttons_layout)

        # Кнопка запуска
        self.run_button = QPushButton("Собрать список тикеров")
        self.run_button.setStyleSheet("""
            QPushButton {
                background-color: #6A5AF9;
                color: white;
                border: none;
                padding: 12px 20px;
                border-radius: 6px;
                font-weight: bold;
                font-size: 14px;
            }
            QPushButton:hover {
                background-color: #5B4AE9;
            }
            QPushButton:disabled {
                background-color: #444444;
                color: #888888;
            }
        """)
        self.run_button.clicked.connect(self.run_parser)
        layout.addWidget(self.run_button)

        # Статус
        self.status_label = QLabel("Готов к работе")
        self.status_label.setAlignment(Qt.AlignCenter)
        self.status_label.setStyleSheet("color: #DDDDDD; font-size: 12px;")
        layout.addWidget(self.status_label)

        # Таймер для обновления статуса
        self.status_timer = QTimer()
        self.status_timer.timeout.connect(self.update_status)
        self.status_messages = []
        self.current_status = ""

        # Анимация для кнопки
        self.animation = QPropertyAnimation(self.run_button, b"geometry")
        self.animation.setDuration(300)
        self.animation.setEasingCurve(QEasingCurve.OutCubic)

    def on_exchange_item_clicked(self, item):
        widget = self.exchange_list.itemWidget(item)
        if widget and isinstance(widget, QCheckBox):
            widget.setChecked(not widget.isChecked())

    def apply_dark_theme(self):
        self.setStyleSheet("""
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

    def filter_exchanges(self):
        text = self.search_input.text()
        self.exchange_list.filter_items(text)

    def update_status(self):
        if self.status_messages:
            self.current_status = self.status_messages.pop(0)
            self.status_label.setText(self.current_status)

    def add_status_message(self, message):
        self.status_messages.append(message)
        if not self.status_timer.isActive():
            self.status_timer.start(100)

    def run_parser(self):
        if self.is_parsing:
            return

        selected_exchanges = self.exchange_list.get_selected_exchanges()
        selected_types = self.instrument_type_widget.get_selected_types()
        filename = self.filename_input.text().strip()

        if not filename:
            QMessageBox.warning(self, "Ошибка", "Введите название файла!")
            return

        if not selected_exchanges:
            QMessageBox.warning(self, "Ошибка", "Выберите хотя бы одну биржу!")
            return

        if not selected_types:
            QMessageBox.warning(self, "Ошибка", "Выберите хотя бы один тип инструмента!")
            return

        # Всегда добавляем расширение .txt, если его нет
        if not filename.endswith('.txt'):
            filename += '.txt'

        # Создаем папку Tickers, если она не существует
        tickers_dir = "Tickers"
        if not os.path.exists(tickers_dir):
            try:
                os.makedirs(tickers_dir)
                self.add_status_message(f"Создана папка {tickers_dir}")
            except Exception as e:
                self.add_status_message(f"Ошибка при создании папки: {str(e)}")
                QMessageBox.critical(self, "Ошибка", f"Не удалось создать папку {tickers_dir}: {str(e)}")
                return

        # Проверяем, существует ли файл
        full_path = os.path.join(tickers_dir, filename)
        if os.path.exists(full_path):
            reply = QMessageBox.question(self, "Файл существует",
                                         f"Файл {filename} уже существует в папке {tickers_dir}. Перезаписать?",
                                         QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if reply == QMessageBox.No:
                self.add_status_message("Операция отменена пользователем")
                return

        self.is_parsing = True
        self.run_button.setEnabled(False)
        self.add_status_message("Запуск парсера...")

        # Анимация нажатия кнопки
        current_geometry = self.run_button.geometry()
        self.animation.setStartValue(current_geometry)
        self.animation.setEndValue(current_geometry.adjusted(0, 5, 0, 5))
        self.animation.start()

        # Запускаем парсер в отдельном потоке
        self.parser_thread = ParserThread(selected_exchanges, selected_types, full_path)
        self.parser_thread.progress_signal.connect(self.add_status_message)
        self.parser_thread.finished_signal.connect(self.on_parser_finished)
        self.parser_thread.error_signal.connect(self.on_parser_error)
        self.parser_thread.start()

    def on_parser_finished(self):
        self.is_parsing = False
        self.run_button.setEnabled(True)

        # Возвращаем кнопку в исходное положение
        current_geometry = self.run_button.geometry()
        self.animation.setStartValue(current_geometry)
        self.animation.setEndValue(current_geometry.adjusted(0, -5, 0, -5))
        self.animation.start()

        self.add_status_message("Парсинг завершен успешно!")
        QMessageBox.information(self, "Успех", "Парсинг завершен успешно!")

    def on_parser_error(self, error_msg):
        self.is_parsing = False
        self.run_button.setEnabled(True)

        # Возвращаем кнопку в исходное положение
        current_geometry = self.run_button.geometry()
        self.animation.setStartValue(current_geometry)
        self.animation.setEndValue(current_geometry.adjusted(0, -5, 0, -5))
        self.animation.start()

        self.add_status_message(f"Ошибка: {error_msg}")

        # Проверяем, является ли ошибка случаем "нет данных"
        if "NO_DATA:" in error_msg:
            # Извлекаем сообщение для пользователя
            user_message = error_msg.split("NO_DATA:")[1]
            QMessageBox.information(self, "Информация", user_message)
        else:
            QMessageBox.critical(self, "Ошибка", f"Произошла ошибка: {error_msg}")

    def closeEvent(self, event):
        # Испускаем сигнал finished при закрытии окна
        self.finished.emit()
        event.accept()


async def tradingview_parser(exchange_names, instrument_types, filename, status_callback):
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        context = await browser.new_context()
        page = await context.new_page()

        try:
            status_callback("Переходим на страницу скринера...")
            await page.goto('https://ru.tradingview.com/cex-screener/', timeout=60000)

            status_callback("Кликаем по кнопке 'Котируемая валюта'...")
            await page.click('text=Котируемая валюта')

            status_callback("Сразу вводим USDT...")
            await page.type('input[placeholder="Поиск"]', 'USDT', delay=100)

            status_callback("Ждем появления результатов...")
            await page.wait_for_timeout(2000)

            status_callback("Выбираем USDT Tether...")
            await page.click('div.middle-LSK1huUA:has-text("Tether USDt")')

            status_callback("Ждем редиректа на страницу авторизации...")
            await page.wait_for_timeout(3000)

            # Сначала авторизация
            status_callback("Ищем iframe с кнопкой Google...")
            iframe = await page.wait_for_selector('iframe.L5Fo6c-PQbLGe', timeout=30000)

            status_callback("Кликаем непосредственно на iframe...")
            box = await iframe.bounding_box()
            await page.mouse.click(box['x'] + box['width'] / 2, box['y'] + box['height'] / 2)

            status_callback("Ждем открытия popup...")
            async with page.expect_popup() as popup_info:
                await page.wait_for_timeout(2000)

            google_popup = await popup_info.value

            status_callback("Вводим email...")
            await google_popup.fill('input[type="email"]', 'ewb9FyQOimE1K@rpilosj.com')
            await google_popup.keyboard.press('Enter')

            status_callback("Ждем загрузки поля пароля...")
            await google_popup.wait_for_timeout(3000)

            status_callback("Вводим пароль...")
            await google_popup.fill('input[type="password"]', 'V9YC0IA20ulov')
            await google_popup.keyboard.press('Enter')

            status_callback("Ожидаем завершения авторизации...")
            await page.wait_for_url('https://ru.tradingview.com/cex-screener/', timeout=30000)
            status_callback("Успешная авторизация!")

            # После авторизации применяем ускоренные методы
            status_callback(f"Применяем фильтр для бирж: {exchange_names}")
            await apply_exchange_filters_fast(page, exchange_names, status_callback)

            # Применяем фильтр по типу инструментов
            status_callback(f"Применяем фильтр для типов инструментов: {instrument_types}")
            await apply_instrument_type_filters_fast(page, instrument_types, status_callback)

            # Ждем загрузки данных и проверяем наличие надписи "Нет подходящих символов"
            status_callback("Проверяем наличие данных...")

            # Даем время для применения фильтров
            await page.wait_for_timeout(3000)

            # Проверяем наличие надписи "Нет подходящих символов"
            no_data_element = await page.query_selector('text=Нет подходящих символов')
            if no_data_element:
                status_callback("На выбранных биржах нет инструментов для выбранных фильтров")
                # Закрываем браузер
                await browser.close()
                # Возвращаем специальный код ошибки для обработки в GUI
                raise Exception("NO_DATA:На выбранных биржах нет инструментов для выбранных фильтров")

            # Если надписи нет, продолжаем обычную обработку
            status_callback("Ожидаем загрузки таблицы...")
            await page.wait_for_selector('.row-RdUXZpkv.listRow', timeout=10000)

            # Прокручиваем таблицу до конца, чтобы загрузились все данные
            status_callback("Прокручиваем таблицу для загрузки всех данных...")
            current_count = await scroll_table_to_bottom_fast(page, status_callback)

            # Парсим все названия монет
            status_callback("Парсим тикеры...")
            tickers = await page.evaluate('''() => {
                const items = [];
                const rows = document.querySelectorAll('.row-RdUXZpkv.listRow');

                for (const row of rows) {
                    const tickerElement = row.querySelector('.tickerName-GrtoTeat');
                    if (tickerElement) {
                        items.push(tickerElement.textContent);
                    }
                }

                return items;
            }''')

            status_callback(f"Найдено {len(tickers)} тикеров")

            # Сохраняем в файл (каждый тикер с новой строки)
            if tickers:
                with open(filename, 'w', encoding='utf-8') as f:
                    for ticker in tickers:
                        f.write(ticker + '\n')
                status_callback(f"Тикеры успешно сохранены в {filename}")
            else:
                status_callback("Не удалось найти тикеры")

            # Закрываем браузер после завершения
            await browser.close()
            status_callback("Браузер закрыт.")

        except Exception as e:
            status_callback(f"Произошла ошибка: {e}")
            try:
                await page.screenshot(path='error_screenshot.png')
            except:
                pass
            try:
                await browser.close()
            except:
                pass
            raise e


async def scroll_table_to_bottom_fast(page, status_callback):
    """Прокручивает таблицу до конца для загрузки всех данных (оптимизированная версия)"""
    status_callback("Начинаем прокрутку таблицы...")

    # Получаем общее количество тикеров из data-matches
    total_matches = await page.evaluate('''() => {
        // Ищем элемент с data-matches, который находится в заголовке столбца "Инструмент"
        const headerCells = document.querySelectorAll('.tickerCellData-cfjBjL5J');
        for (let cell of headerCells) {
            let headerText = cell.querySelector('.headCellTitle-MSg2GmPp');
            if (headerText && headerText.textContent.includes('Инструмент')) {
                let matchesElem = cell.querySelector('[data-matches]');
                if (matchesElem) {
                    return parseInt(matchesElem.getAttribute('data-matches'));
                }
            }
        }
        return 0;
    }''')

    # Если data-matches не найдено, проверяем наличие строк в таблице
    if total_matches == 0:
        # Проверяем, есть ли вообще строки в таблице
        rows_count = await page.evaluate('''() => {
            return document.querySelectorAll('.row-RdUXZpkv.listRow').length;
        }''')

        if rows_count == 0:
            status_callback("На выбранных биржах нет тикеров для выбранных фильтров")
            raise Exception("На выбранных биржах нет тикеров для выбранных фильтров")
        else:
            # Если строки есть, но data-matches не найдено, используем количество строк
            total_matches = rows_count
            status_callback(f"Найдено {total_matches} тикеров (data-matches не доступен)")

    status_callback(f"Общее количество тикеров: {total_matches}")

    # Находим контейнер таблицы
    table_container = await page.query_selector('div[data-name="screener-table"]')
    if not table_container:
        table_container = await page.query_selector('.table-Ngq2xrcG')

    max_scroll_attempts = 20
    scroll_attempts = 0
    last_count = 0
    current_count = 0

    while scroll_attempts < max_scroll_attempts:
        # Получаем текущее количество элементов
        current_count = await page.evaluate('''() => {
            return document.querySelectorAll('.row-RdUXZpkv.listRow').length;
        }''')

        status_callback(f"Текущее количество тикеров: {current_count}")

        # Если достигли общего количества тикеров, ВЫХОДИМ НЕМЕДЛЕННО
        if total_matches > 0 and current_count >= total_matches:
            status_callback(f"Достигнуто общее количество тикеров: {total_matches}")
            return current_count  # Немедленно возвращаем результат

        # Если количество не изменилось с последней проверки, увеличиваем счетчик попыток
        if current_count == last_count:
            scroll_attempts += 1
            status_callback(f"Количество не изменилось. Попытка {scroll_attempts}/{max_scroll_attempts}")
        else:
            scroll_attempts = 0  # Сбрасываем счетчик, если есть прогресс

        last_count = current_count

        # Прокручиваем к последнему элементу
        await page.evaluate('''() => {
            const rows = document.querySelectorAll('.row-RdUXZpkv.listRow');
            if (rows.length > 0) {
                rows[rows.length - 1].scrollIntoView();
            }
        }''')

        # Увеличиваем время ожидания для надежности
        await page.wait_for_timeout(2000)

        # Если достигли максимального количества попыток, выходим
        if scroll_attempts >= max_scroll_attempts:
            status_callback("Достигнут лимит попыток прокрутки")
            break

    status_callback(f"Завершение прокрутки. Итого тикеров: {current_count}")
    return current_count


async def apply_exchange_filters_fast(page, exchange_names, status_callback):
    """Оптимизированное применение фильтров по биржам (после авторизации)"""
    status_callback("Кликаем по кнопке 'Биржа'...")
    await page.click('text=Биржа')

    # Ждем появления поле поиска
    search_input = await page.wait_for_selector('input[placeholder="Поиск"]', timeout=5000)

    for exchange_name in exchange_names:
        status_callback(f"Выбираем биржу: {exchange_name}")

        # Очищаем поле поиска быстрым способом
        await search_input.click(click_count=3)
        await search_input.press('Backspace')

        # Вводим название биржи с минимальной задержкой
        await search_input.type(exchange_name, delay=50)

        # Ждем появления результатов
        await page.wait_for_timeout(500)

        # Выбираем биржу из списка
        try:
            await page.click(f'div.middle-LSK1huUA:has-text("{exchange_name}")', timeout=3000)
            status_callback(f"Биржа {exchange_name} выбрана успешно")
        except Exception as e:
            status_callback(f"Не удалось выбрать биржу {exchange_name}: {e}")

        # Минимальная пауза перед следующей биржей
        await page.wait_for_timeout(300)

    # Закрываем окно выбора бирж
    await page.keyboard.press('Escape')
    status_callback("Все биржи выбраны успешно!")


async def apply_instrument_type_filters_fast(page, instrument_types, status_callback):
    """Оптимизированное применение фильтров по типам инструментов (после авторизации)"""
    status_callback("Кликаем по кнопке 'Тип инструмента'...")
    await page.click('text=Тип инструмента')

    # Ждем появления меню
    await page.wait_for_timeout(1000)

    for instrument_type in instrument_types:
        status_callback(f"Выбираем тип инструмента: {instrument_type}")

        # Выбираем тип инструмента из списка
        try:
            await page.click(f'div.middle-LSK1huUA:has-text("{instrument_type}")', timeout=2000)
            status_callback(f"Тип инструмента {instrument_type} выбран успешно")
        except Exception as e:
            status_callback(f"Не удалось выбрать тип инструмента {instrument_type}: {e}")

        # Минимальная пауза перед следующим типом
        await page.wait_for_timeout(200)

    # Закрываем окно выбора типов инструментов
    await page.keyboard.press('Escape')
    status_callback("Все типы инструментов выбраны успешно!")


if __name__ == "__main__":
    app = QApplication(sys.argv)

    # Настройка asyncio для работы с Qt
    from qasync import QEventLoop

    loop = QEventLoop(app)
    asyncio.set_event_loop(loop)

    window = TradingViewParserGUI()
    window.show()

    with loop:
        sys.exit(loop.run_forever())