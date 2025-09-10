# freak_parser.py
# CDP-attach к реальному Chrome (или автозапуск). Хранение сессии в отдельном профиле.
# Тумблер NEED_LOGIN_FIRST_TIME:
#   True  -> открыть окно логина один раз (ручной вход), потом работать по кукам
#   False -> сразу работать по кукам, без лишних ожиданий
# Переключатель USE_HEADLESS_CHROME:
#   Работает только если профиль уже авторизован (ручной вход невозможен в headless).

import asyncio
import os
import sys
import time
import subprocess

from PyQt5.QtWidgets import (
    QApplication, QPushButton, QVBoxLayout, QWidget, QLabel, QLineEdit,
    QListWidget, QListWidgetItem, QCheckBox, QHBoxLayout, QMessageBox,
    QGroupBox, QDialog
)
from PyQt5.QtCore import Qt, QTimer, QPropertyAnimation, QEasingCurve, QThread, pyqtSignal
from playwright.async_api import async_playwright

# ===================== НАСТРОЙКИ =====================

# Путь к Chrome (проверь у друга)
CHROME_EXE = r"C:\Program Files\Google\Chrome\Application\chrome.exe"

# CDP endpoint
CDP_HOST = "127.0.0.1"
CDP_PORT = 9222
CDP_ENDPOINT = f"http://{CDP_HOST}:{CDP_PORT}"

# Отдельный профиль (куки/сессия тут)
CDP_USER_DATA_DIR = r"C:\ChromeTV"

# Сколько ждать подъём CDP при автозапуске
CDP_STARTUP_TIMEOUT_SEC = 20

# --- Главный тумблер: нужен ли первый ручной вход сейчас? ---
NEED_LOGIN_FIRST_TIME = False   # поставь True, если в этом профиле ещё не логинился

# Headless для запускаемого нами Chrome (включай только когда логин уже есть)
USE_HEADLESS_CHROME = False

# «Быстрый режим» (минимум ожиданий), если логин не нужен
FAST_WAIT_MS = 250
SLOW_WAIT_MS = 1200

# Таймауты (быстрый/медленный)
NAV_TIMEOUT_MS_FAST = 40_000
NAV_TIMEOUT_MS_SLOW = 90_000
SEL_TIMEOUT_MS_FAST = 7_000
SEL_TIMEOUT_MS_SLOW = 25_000


# ===================== UI =====================

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
                    color: #DDDDDD; background-color: transparent;
                    font-size: 13px; padding: 5px; spacing: 8px;
                }
                QCheckBox::indicator {
                    width: 18px; height: 18px; border: 2px solid #555555;
                    border-radius: 4px; background-color: #3A3A3A;
                }
                QCheckBox::indicator:checked { border: 2px solid #6A5AF9; background-color: #6A5AF9; }
                QCheckBox::indicator:unchecked:hover { border: 2px solid #777777; }
                QCheckBox::indicator:checked:hover { border: 2px solid #5B4AE9; background-color: #5B4AE9; }
            """)
            checkbox.setChecked(False)
            self.setItemWidget(item, checkbox)

    def get_selected_exchanges(self):
        res = []
        for i in range(self.count()):
            w = self.itemWidget(self.item(i))
            if w.isChecked():
                res.append(w.text())
        return res

    def select_all(self):
        for i in range(self.count()):
            self.itemWidget(self.item(i)).setChecked(True)

    def deselect_all(self):
        for i in range(self.count()):
            self.itemWidget(self.item(i)).setChecked(False)

    def filter_items(self, text):
        low = text.lower()
        for i in range(self.count()):
            it = self.item(i)
            w = self.itemWidget(it)
            it.setHidden(low not in w.text().lower())


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
                background-color: #2D2D2D; border: 1px solid #444444; border-radius: 8px;
                margin-top: 1ex; padding: 15px; color: #DDDDDD; font-weight: bold; font-size: 14px;
            }
            QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 5px; background: transparent; }
        """)
        gl = QVBoxLayout(group)

        self.spot = QCheckBox("Спот")
        self.fut = QCheckBox("Фьючерсы")
        self.perp = QCheckBox("Бессрочные контракты")

        css = """
            QCheckBox { color:#DDDDDD; background:transparent; font-size:12px; padding:5px; }
            QCheckBox::indicator { width:16px; height:16px; }
            QCheckBox::indicator:unchecked { border:1px solid #555555; background:#3A3A3A; border-radius:3px; }
            QCheckBox::indicator:checked   { border:1px solid #6A5AF9; background:#6A5AF9; border-radius:3px; }
        """
        for cb in (self.spot, self.fut, self.perp):
            cb.setStyleSheet(css)
            gl.addWidget(cb)

        row = QHBoxLayout()
        b1 = QPushButton("Выбрать все"); b1.setStyleSheet(
            "QPushButton{background:#6A5AF9;color:#fff;border:none;padding:8px 15px;border-radius:4px;font-size:12px;}QPushButton:hover{background:#5B4AE9;}")
        b2 = QPushButton("Снять все");   b2.setStyleSheet(
            "QPushButton{background:#444;color:#DDD;border:none;padding:8px 15px;border-radius:4px;font-size:12px;}QPushButton:hover{background:#555;}")
        b1.clicked.connect(self.select_all); b2.clicked.connect(self.deselect_all)
        row.addWidget(b1); row.addWidget(b2); gl.addLayout(row)

        layout.addWidget(group)

    def get_selected_types(self):
        res = []
        if self.spot.isChecked(): res.append("Спот")
        if self.fut.isChecked(): res.append("Фьючерсы")
        if self.perp.isChecked(): res.append("Бессрочные контракты")
        return res

    def select_all(self):
        self.spot.setChecked(True); self.fut.setChecked(True); self.perp.setChecked(True)

    def deselect_all(self):
        self.spot.setChecked(False); self.fut.setChecked(False); self.perp.setChecked(False)


class ParserThread(QThread):
    progress_signal = pyqtSignal(str)
    finished_signal = pyqtSignal()
    error_signal = pyqtSignal(str)

    def __init__(self, exchanges, types_, filename):
        super().__init__()
        self.exchanges = exchanges
        self.types_ = types_
        self.filename = filename

    def run(self):
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(tradingview_parser(
                self.exchanges, self.types_, self.filename, self.progress_signal.emit
            ))
            self.finished_signal.emit()
        except Exception as e:
            self.error_signal.emit(str(e))


class TradingViewParserGUI(QDialog):
    finished = pyqtSignal()

    def __init__(self):
        super().__init__()
        self.setWindowTitle("TradingView Parser — Chrome (CDP)")
        self.setGeometry(100, 100, 900, 900)
        self.is_parsing = False
        self.apply_dark_theme()

        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 20, 20, 20)
        lay.setSpacing(15)

        title = QLabel("Настройки парсера TradingView")
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet("font-size:18px;font-weight:bold;color:#DDD;")
        lay.addWidget(title)

        row = QHBoxLayout()
        row.addWidget(QLabel("Название TXT файла:"))
        self.filename = QLineEdit("tickers")
        self.filename.setPlaceholderText("Введите название файла...")
        self.filename.setStyleSheet(
            "QLineEdit{background:#3A3A3A;color:#DDD;border:1px solid #555;border-radius:4px;padding:8px 12px;font-size:13px;}")
        row.addWidget(self.filename)
        lay.addLayout(row)

        self.types = InstrumentTypeWidget()
        lay.addWidget(self.types)

        srow = QHBoxLayout()
        srow.addWidget(QLabel("Поиск бирж:"))
        self.search = QLineEdit()
        self.search.setPlaceholderText("Введите название биржи...")
        self.search.setStyleSheet(
            "QLineEdit{background:#3A3A3A;color:#DDD;border:1px solid #555;border-radius:4px;padding:8px 12px;font-size:13px;}")
        self.search.textChanged.connect(self.filter_exchanges)
        srow.addWidget(self.search)
        lay.addLayout(srow)

        lay.addWidget(QLabel("Выберите биржи:"))
        self.exlist = ExchangeListWidget()
        self.exlist.setStyleSheet("""
            QListWidget{background:#3A3A3A;color:#DDD;border:1px solid #555;border-radius:4px;font-size:13px;}
            QListWidget::item{padding:8px 12px;border-bottom:1px solid #444;height:30px;}
            QListWidget::item:hover{background:#4A4A4A;}
        """)
        self.exlist.itemClicked.connect(self.on_ex_item_clicked)
        lay.addWidget(self.exlist)

        buttons = QHBoxLayout()
        b_all = QPushButton("Выбрать все"); b_all.setStyleSheet(
            "QPushButton{background:#6A5AF9;color:#fff;border:none;padding:8px 15px;border-radius:4px;font-size:12px;}QPushButton:hover{background:#5B4AE9;}")
        b_none = QPushButton("Снять все");   b_none.setStyleSheet(
            "QPushButton{background:#444;color:#DDD;border:none;padding:8px 15px;border-radius:4px;font-size:12px;}QPushButton:hover{background:#555;}")
        b_all.clicked.connect(self.exlist.select_all); b_none.clicked.connect(self.exlist.deselect_all)
        buttons.addWidget(b_all); buttons.addWidget(b_none); lay.addLayout(buttons)

        self.run_btn = QPushButton("Собрать список тикеров")
        self.run_btn.setStyleSheet("""
            QPushButton{background:#6A5AF9;color:#fff;border:none;padding:12px 20px;border-radius:6px;font-weight:bold;font-size:14px;}
            QPushButton:hover{background:#5B4AE9;} QPushButton:disabled{background:#444;color:#888;}
        """)
        self.run_btn.clicked.connect(self.run_parser)
        lay.addWidget(self.run_btn)

        self.status = QLabel("Готов к работе")
        self.status.setAlignment(Qt.AlignCenter)
        self.status.setStyleSheet("color:#DDD;font-size:12px;")
        lay.addWidget(self.status)

        self.tmr = QTimer()
        self.tmr.timeout.connect(self._flush_status)
        self._q = []

        self.anim = QPropertyAnimation(self.run_btn, b"geometry")
        self.anim.setDuration(300)
        self.anim.setEasingCurve(QEasingCurve.OutCubic)

    def on_ex_item_clicked(self, item):
        w = self.exlist.itemWidget(item)
        if w and isinstance(w, QCheckBox):
            w.setChecked(not w.isChecked())  # toggle

    def apply_dark_theme(self):
        self.setStyleSheet(
            "QWidget{background:#1E1E1E;color:#DDD;} QToolTip{background:#3A3A3A;color:#DDD;border:1px solid #555;border-radius:4px;padding:5px;}")

    def filter_exchanges(self):
        self.exlist.filter_items(self.search.text())

    def _flush_status(self):
        if self._q:
            self.status.setText(self._q.pop(0))

    def log(self, msg):
        self._q.append(msg)
        if not self.tmr.isActive():
            self.tmr.start(100)

    def run_parser(self):
        if self.is_parsing:
            return

        exchanges = self.exlist.get_selected_exchanges()
        types_ = self.types.get_selected_types()
        filename = self.filename.text().strip()

        if not filename:
            QMessageBox.warning(self, "Ошибка", "Введите название файла!")
            return
        if not exchanges:
            QMessageBox.warning(self, "Ошибка", "Выберите хотя бы одну биржу!")
            return
        if not types_:
            QMessageBox.warning(self, "Ошибка", "Выберите хотя бы один тип инструмента!")
            return
        if not filename.endswith(".txt"):
            filename += ".txt"

        os.makedirs("Tickers", exist_ok=True)
        full_path = os.path.join("Tickers", filename)

        if os.path.exists(full_path):
            if QMessageBox.question(self, "Файл существует", f"{filename} уже есть. Перезаписать?",
                                    QMessageBox.Yes | QMessageBox.No, QMessageBox.No) == QMessageBox.No:
                self.log("Операция отменена пользователем")
                return

        self.is_parsing = True
        self.run_btn.setEnabled(False)
        self.log("Запуск парсера (CDP attach)...")
        g = self.run_btn.geometry()
        self.anim.setStartValue(g)
        self.anim.setEndValue(g.adjusted(0, 5, 0, 5))
        self.anim.start()

        self.thread = ParserThread(exchanges, types_, full_path)
        self.thread.progress_signal.connect(self.log)
        self.thread.finished_signal.connect(self._ok)
        self.thread.error_signal.connect(self._err)
        self.thread.start()

    def _ok(self):
        self.is_parsing = False
        self.run_btn.setEnabled(True)
        g = self.run_btn.geometry()
        self.anim.setStartValue(g)
        self.anim.setEndValue(g.adjusted(0, -5, 0, -5))
        self.anim.start()
        self.log("Парсинг завершён успешно!")
        QMessageBox.information(self, "Успех", "Парсинг завершён успешно!")

    def _err(self, msg):
        self.is_parsing = False
        self.run_btn.setEnabled(True)
        g = self.run_btn.geometry()
        self.anim.setStartValue(g)
        self.anim.setEndValue(g.adjusted(0, -5, 0, -5))
        self.anim.start()
        self.log(f"Ошибка: {msg}")
        if "NO_DATA:" in msg:
            QMessageBox.information(self, "Информация", msg.split("NO_DATA:")[1])
        else:
            QMessageBox.critical(self, "Ошибка", f"Произошла ошибка: {msg}")

    def closeEvent(self, e):
        self.finished.emit()
        e.accept()


# ===================== CDP ХЕЛПЕРЫ =====================

def _build_chrome_cmd():
    os.makedirs(CDP_USER_DATA_DIR, exist_ok=True)
    cmd = [
        CHROME_EXE,
        f"--remote-debugging-port={CDP_PORT}",
        f'--user-data-dir={CDP_USER_DATA_DIR}',
        "--no-first-run", "--no-default-browser-check"
    ]
    if USE_HEADLESS_CHROME:
        cmd.append("--headless=new")
    return cmd

async def _connect_or_launch_cdp(p, log):
    """
    Пытаемся подключиться к существующему CDP.
    Если не вышло — запускаем Chrome сами. Возвращаем (browser, context, launched, proc).
    """
    # 1) Подключаемся к уже запущенному Chrome
    try:
        log(f"Пробую подключиться к CDP: {CDP_ENDPOINT}...")
        br = await p.chromium.connect_over_cdp(CDP_ENDPOINT)
        ctx = br.contexts[0] if br.contexts else await br.new_context()
        log("CDP подключение установлено (подцепился к уже запущенному Chrome).")
        return br, ctx, False, None
    except Exception:
        log("CDP недоступен. Запускаю Chrome сам...")

    # 2) Запускаем Chrome
    launched_proc = None
    try:
        launched_proc = subprocess.Popen(
            _build_chrome_cmd(),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=(subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        )
    except Exception as e:
        raise RuntimeError(f"Не удалось запустить Chrome: {e}")

    # 3) Ждём, пока поднимется CDP
    start = time.time()
    last_err = None
    while time.time() - start < CDP_STARTUP_TIMEOUT_SEC:
        try:
            br = await p.chromium.connect_over_cdp(CDP_ENDPOINT)
            ctx = br.contexts[0] if br.contexts else await br.new_context()
            log("Chrome запущен и CDP готов.")
            return br, ctx, True, launched_proc
        except Exception as e:
            last_err = e
            await asyncio.sleep(0.5)

    # Если не поднялся — гасим процесс
    try:
        if launched_proc and launched_proc.poll() is None:
            if os.name == "nt":
                subprocess.run(["taskkill", "/F", "/T", "/PID", str(launched_proc.pid)],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            else:
                launched_proc.terminate()
    except Exception:
        pass
    raise RuntimeError(f"CDP не поднялся за {CDP_STARTUP_TIMEOUT_SEC} сек. Последняя ошибка: {last_err}")

async def _ensure_login_if_needed(page, log, fast_mode: bool):
    """
    Если NEED_LOGIN_FIRST_TIME=True → ведём на /#signin и ждём меню пользователя.
    Если False → ничего не делаем (сразу работаем).
    """
    # Настрой таймауты согласно режиму
    page.set_default_timeout(SEL_TIMEOUT_MS_FAST if fast_mode else SEL_TIMEOUT_MS_SLOW)
    page.set_default_navigation_timeout(NAV_TIMEOUT_MS_FAST if fast_mode else NAV_TIMEOUT_MS_SLOW)

    if not NEED_LOGIN_FIRST_TIME:
        # Лёгкий прогрев домена (best effort), но без падений
        try:
            await page.goto(
                "https://ru.tradingview.com/",
                timeout=(NAV_TIMEOUT_MS_FAST if fast_mode else NAV_TIMEOUT_MS_SLOW)
            )
        except Exception:
            pass
        return

    # Нужен первый вход
    if USE_HEADLESS_CHROME:
        raise RuntimeError("Нужна авторизация TradingView. Выключи headless (USE_HEADLESS_CHROME=False) и войди один раз.")

    log("Первый вход: открываю https://ru.tradingview.com/#signin — войди в аккаунт (можно Google).")
    await page.goto(
        "https://ru.tradingview.com/#signin",
        timeout=(NAV_TIMEOUT_MS_FAST if fast_mode else NAV_TIMEOUT_MS_SLOW)
    )

    # ждём до 5 минут появления признака входа
    timeout_ms = 300_000
    step = 5_000
    waited = 0
    while waited < timeout_ms:
        try:
            if await page.locator('text=Профиль, text=Profile, [data-name="header-user-menu-button"]').first.is_visible():
                log("Вход подтверждён. Продолжаем.")
                return
        except Exception:
            pass
        await asyncio.sleep(step / 1000)
        waited += step
        log("Жду подтверждение входа...")

    log("Не дождался подтверждения входа — продолжаю (возможно уже OK).")


# ===================== ЛОГИКА СТРАНИЦЫ (селекторы как раньше) =====================

async def _click_text_any(page, texts, timeout=3000):
    for t in texts:
        try:
            await page.click(f'text={t}', timeout=timeout)
            return True
        except Exception:
            continue
    return False

async def apply_exchange_filters_fast(page, exch, log, fast_mode: bool):
    log("Открываю фильтр Биржа/Exchange...")
    if not await _click_text_any(page, ["Биржа", "Exchange"], timeout=5000):
        raise Exception("Не нашёл кнопку 'Биржа/Exchange'")

    search_input = await page.wait_for_selector('input[placeholder="Поиск"], input[placeholder="Search"]', timeout=5000)
    for name in exch:
        await search_input.click(click_count=3)
        await search_input.press('Backspace')
        await search_input.type(name, delay=0 if fast_mode else 50)
        await page.wait_for_timeout(FAST_WAIT_MS if fast_mode else 500)
        try:
            await page.click(f'div.middle-LSK1huUA:has-text("{name}")', timeout=3000)
        except Exception as e:
            log(f"Не получилось выбрать биржу {name}: {e}")
        await page.wait_for_timeout(FAST_WAIT_MS if fast_mode else 300)

    await page.keyboard.press('Escape')
    log("Все биржи выбраны успешно!")

async def apply_instrument_type_filters_fast(page, types_, log, fast_mode: bool):
    log("Открываю фильтр Тип инструмента/Instrument type...")
    if not await _click_text_any(page, ["Тип инструмента", "Instrument type"], timeout=5000):
        raise Exception("Не нашёл кнопку 'Тип инструмента/Instrument type'")
    await page.wait_for_timeout(FAST_WAIT_MS if fast_mode else 1000)

    for t in types_:
        try:
            await page.click(f'div.middle-LSK1huUA:has-text("{t}")', timeout=2000)
            log(f"Тип инструмента {t} выбран успешно")
        except Exception as e:
            log(f"Не удалось выбрать тип инструмента {t}: {e}")
        await page.wait_for_timeout(FAST_WAIT_MS if fast_mode else 200)

    await page.keyboard.press('Escape')
    log("Все типы инструментов выбраны успешно!")

# НОВОЕ: централизованная проверка «нет данных»
async def _fail_if_no_symbols(page, log, exchanges, types_):
    try:
        banner = page.locator('text=Нет подходящих символов, text=No symbols match').first
        if await banner.is_visible():
            msg = f"На выбранных биржах ({', '.join(exchanges)}) нет инструментов для типов: {', '.join(types_)}"
            raise Exception(f"NO_DATA:{msg}")
    except Exception:
        pass
    try:
        rows = await page.evaluate('''() => document.querySelectorAll('.row-RdUXZpkv.listRow').length''')
    except Exception:
        rows = 0
    if rows == 0:
        msg = f"На выбранных биржах ({', '.join(exchanges)}) нет инструментов для типов: {', '.join(types_)}"
        raise Exception(f"NO_DATA:{msg}")

# СТАРАЯ ЛОГИКА: докручиваем строго до data-matches
async def scroll_table_to_bottom_fast(page, log, fast_mode: bool):
    """Прокручивает таблицу до конца, строго до total_matches из data-matches (как было раньше)."""
    log("Начинаем прокрутку таблицы...")

    total_matches = await page.evaluate('''() => {
        const headerCells = document.querySelectorAll('.tickerCellData-cfjBjL5J');
        for (let cell of headerCells) {
            let headerText = cell.querySelector('.headCellTitle-MSg2GmPp');
            if (headerText && headerText.textContent.includes('Инструмент')) {
                let matchesElem = cell.querySelector('[data-matches]');
                if (matchesElem) return parseInt(matchesElem.getAttribute('data-matches'));
            }
        }
        return 0;
    }''')

    if total_matches == 0:
        rows_count = await page.evaluate('''() => {
            return document.querySelectorAll('.row-RdUXZpkv.listRow').length;
        }''')
        if rows_count == 0:
            log("На выбранных биржах нет тикеров для выбранных фильтров")
            raise Exception("NO_DATA:На выбранных биржах нет тикеров для выбранных фильтров")
        else:
            total_matches = rows_count
            log(f"Найдено {total_matches} тикеров (data-matches не доступен)")

    log(f"Общее количество тикеров: {total_matches}")

    table_container = await page.query_selector('div[data-name="screener-table"]')
    if not table_container:
        table_container = await page.query_selector('.table-Ngq2xrcG')

    max_scroll_attempts = 20
    scroll_attempts = 0
    last_count = 0
    current_count = 0

    while scroll_attempts < max_scroll_attempts:
        current_count = await page.evaluate('''() => {
            return document.querySelectorAll('.row-RdUXZpkv.listRow').length;
        }''')

        log(f"Текущее количество тикеров: {current_count}")

        if total_matches > 0 and current_count >= total_matches:
            log(f"Достигнуто общее количество тикеров: {total_matches}")
            return current_count

        if current_count == last_count:
            scroll_attempts += 1
            log(f"Количество не изменилось. Попытка {scroll_attempts}/{max_scroll_attempts}")
        else:
            scroll_attempts = 0

        last_count = current_count

        await page.evaluate('''() => {
            const rows = document.querySelectorAll('.row-RdUXZpkv.listRow');
            if (rows.length > 0) {
                rows[rows.length - 1].scrollIntoView();
            }
        }''')

        await page.wait_for_timeout(2000)

        if scroll_attempts >= max_scroll_attempts:
            log("Достигнут лимит попыток прокрутки")
            break

    log(f"Завершение прокрутки. Итого тикеров: {current_count}")
    return current_count


# ===================== ОСНОВНОЙ ПАРСЕР =====================

async def tradingview_parser(exchange_names, instrument_types, filename, log):
    async with async_playwright() as p:
        browser = None
        context = None
        page = None
        launched = False
        launched_proc = None

        fast_mode = not NEED_LOGIN_FIRST_TIME

        try:
            # 1) attach (или автозапуск Chrome)
            browser, context, launched, launched_proc = await _connect_or_launch_cdp(p, log)
            page = await context.new_page()
            page.set_default_timeout(SEL_TIMEOUT_MS_FAST if fast_mode else SEL_TIMEOUT_MS_SLOW)
            page.set_default_navigation_timeout(NAV_TIMEOUT_MS_FAST if fast_mode else NAV_TIMEOUT_MS_SLOW)
            try:
                await page.bring_to_front()
            except Exception:
                pass

            # 2) первый вход (если требуется)
            await _ensure_login_if_needed(page, log, fast_mode)

            # 3) идём в скринер
            log("Открываю CEX-скринер...")
            await page.goto(
                "https://ru.tradingview.com/cex-screener/",
                timeout=(NAV_TIMEOUT_MS_FAST if fast_mode else NAV_TIMEOUT_MS_SLOW),
                wait_until="domcontentloaded"
            )

            # 4) Котируемая валюта → USDT
            log("Выбираю 'Котируемая валюта / Quote currency'...")
            if not await _click_text_any(page, ["Котируемая валюта", "Quote currency"], timeout=5000):
                raise Exception("Не нашёл кнопку 'Котируемая валюта/Quote currency'")

            await page.type('input[placeholder="Поиск"], input[placeholder="Search"]', 'USDT',
                            delay=0 if fast_mode else 70)
            await page.wait_for_timeout(FAST_WAIT_MS if fast_mode else 900)

            try:
                await page.click('div.middle-LSK1huUA:has-text("Tether USDt")', timeout=3000)
            except Exception:
                try:
                    await page.click('div.middle-LSK1huUA:has-text("USDT")', timeout=2000)
                except Exception as e:
                    log(f"Не удалось выбрать USDT: {e}")

            # 5) фильтры
            await apply_exchange_filters_fast(page, exchange_names, log, fast_mode)
            await apply_instrument_type_filters_fast(page, instrument_types, log, fast_mode)

            # 6) проверка «Нет подходящих символов»
            await page.wait_for_timeout(FAST_WAIT_MS if fast_mode else 1200)
            await _fail_if_no_symbols(page, log, exchange_names, instrument_types)

            # 7) ждём появления строк и скроллим до total_matches
            await page.wait_for_selector(
                '.row-RdUXZpkv.listRow',
                timeout=(SEL_TIMEOUT_MS_FAST if fast_mode else SEL_TIMEOUT_MS_SLOW)
            )

            await scroll_table_to_bottom_fast(page, log, fast_mode)

            # 8) парс тикеров
            log("Парсю тикеры...")
            tickers = await page.evaluate('''() => {
                const out=[];
                document.querySelectorAll('.row-RdUXZpkv.listRow').forEach(r=>{
                    const el=r.querySelector('.tickerName-GrtoTeat');
                    if(el) out.push(el.textContent);
                });
                return out;
            }''')
            log(f"Найдено {len(tickers)} тикеров")

            os.makedirs(os.path.dirname(filename) or ".", exist_ok=True)
            with open(filename, 'w', encoding='utf-8') as f:
                for t in tickers:
                    f.write(t + "\n")
            log(f"Тикеры сохранены: {filename}")

            # 9) Закрытие
            try:
                await page.close()
            except Exception:
                pass

            # Если запускали Chrome сами — закрываем его
            if launched:
                log("Закрываю запущенный Chrome...")
                try:
                    await browser.close()
                except Exception:
                    pass
                try:
                    if launched_proc and launched_proc.poll() is None:
                        if os.name == "nt":
                            subprocess.run(["taskkill", "/F", "/T", "/PID", str(launched_proc.pid)],
                                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                        else:
                            launched_proc.terminate()
                except Exception:
                    pass
            else:
                log("Chrome был уже запущен — оставляю как есть.")

            log("Готово.")

        except Exception as e:
            log(f"Ошибка: {e}")
            try:
                if page:
                    await page.screenshot(path='error_screenshot.png')
            except Exception:
                pass

            # В случае ошибки тоже закрываем наш Chrome, если запускали
            try:
                if launched:
                    try:
                        await browser.close()
                    except Exception:
                        pass
                    if launched_proc and launched_proc.poll() is None:
                        if os.name == "nt":
                            subprocess.run(["taskkill", "/F", "/T", "/PID", str(launched_proc.pid)],
                                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                        else:
                            launched_proc.terminate()
            except Exception:
                pass

            raise


# ===================== ENTRY =====================

if __name__ == "__main__":
    app = QApplication(sys.argv)
    from qasync import QEventLoop
    loop = QEventLoop(app)
    asyncio.set_event_loop(loop)

    win = TradingViewParserGUI()
    win.show()

    with loop:
        sys.exit(loop.run_forever())
