import time
import random
import sys
import os
from pathlib import Path
import logging
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError
import multiprocessing
import threading
from queue import Queue
from datetime import datetime, timedelta
import concurrent.futures
from tqdm import tqdm
import re  # для нормализации имён бирж

multiprocessing.freeze_support()

# Настройка логирования
logger = logging.getLogger('TradingViewParser')
logger.setLevel(logging.INFO)

if not logger.handlers:
    file_handler = logging.FileHandler("crypto_scanner.log", encoding='utf-8')
    file_handler.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))
    logger.addHandler(file_handler)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))
    logger.addHandler(console_handler)


def _normalize_exchange_name(text: str) -> str:
    """
    Убирает букву-лого из начала/конца и дубликаты:
    "B Binance" -> "Binance", "Binance, B" -> "Binance", "OKX OKX" -> "OKX"
    """
    if not text:
        return ""
    s = text.replace('\xa0', ' ').replace('\n', ' ')
    s = " ".join(s.split())  # схлопываем пробелы

    # убираем ведущую одиночную букву-лого
    s = re.sub(r'^[A-Za-zА-Яа-я]\s+', '', s)
    # убираем хвост ", X" где X — одиночная буква
    s = re.sub(r',\s*[A-Za-zА-Яа-я]$', '', s)

    # убираем подряд идущие дубли слов ("OKX OKX" -> "OKX")
    parts = s.split()
    dedup = [w for i, w in enumerate(parts) if i == 0 or w != parts[i - 1]]
    s = " ".join(dedup)

    return s.strip()


class TradingViewParser:
    _browser = None
    _playwright = None
    _browser_lock = threading.Lock()
    _instance_count = 0

    def __init__(self, headless=True, instance_id="default"):
        self.headless = headless
        self.instance_id = instance_id
        self.context = None
        self.page = None
        self._closed = False

        with TradingViewParser._browser_lock:
            TradingViewParser._instance_count += 1

        # Инициализируем браузер только если он еще не создан
        if TradingViewParser._browser is None:
            self._init_browser()

    def _init_browser(self):
        """Инициализация браузера (только один раз)"""
        with TradingViewParser._browser_lock:
            if TradingViewParser._browser is None:
                try:
                    TradingViewParser._playwright = sync_playwright().start()

                    launch_options = {
                        "headless": self.headless,
                        "args": [
                            "--disable-blink-features=AutomationControlled",
                            "--disable-infobars",
                            "--disable-web-security",
                            "--disable-site-isolation-trials",
                            "--disable-features=IsolateOrigins,site-per-process",
                            "--disable-dev-shm-usage",
                            "--no-sandbox",
                            "--disable-gpu",
                            "--disable-software-rasterizer",
                            "--disable-setuid-sandbox",
                            "--disable-breakpad",
                            "--disable-background-networking",
                            "--disable-default-apps",
                            "--disable-extensions",
                            "--disable-sync",
                            "--disable-translate",
                            "--metrics-recording-only",
                            "--no-first-run",
                            "--mute-audio",
                            "--safebrowsing-disable-auto-update",
                            "--ignore-certificate-errors",
                            "--aggressive-cache-discard",
                            "--disable-application-cache",
                            "--disable-offline-load-stale-cache",
                            "--disk-cache-size=0",
                            "--media-cache-size=0",
                        ],
                        "timeout": 60000
                    }

                    TradingViewParser._browser = TradingViewParser._playwright.chromium.launch(**launch_options)
                    logger.info("Браузер успешно запущен")
                except Exception as e:
                    logger.error(f"Ошибка при запуске браузера: {str(e)}")
                    raise

    def _create_context(self):
        """Создает новый контекст браузера"""
        if TradingViewParser._browser is None:
            self._init_browser()

        self.context = TradingViewParser._browser.new_context(
            locale="ru-RU",
            timezone_id="Europe/Moscow",
            permissions=[],
            geolocation={"longitude": random.uniform(30, 40), "latitude": random.uniform(50, 60)},
            color_scheme="light",
            ignore_https_errors=True,
            java_script_enabled=True,
            offline=False,
            storage_state=None,
            viewport={"width": 1280, "height": 720}
        )

        # Антидетект мелочи
        self.context.add_init_script("""
            delete navigator.__proto__.webdriver;
            Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
            Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
            Object.defineProperty(navigator, 'languages', { get: () => ['ru-RU', 'ru'] });
        """)

        # Режем тяжелые/лишние ресурсы (ускорение)
        def _route_handler(route, request):
            rtype = request.resource_type
            url = request.url
            if rtype in ("image", "media", "font", "beacon"):
                return route.abort()
            bad = ("googletagmanager", "google-analytics", "doubleclick", "facebook", "sentry", "hotjar")
            if any(b in url for b in bad):
                return route.abort()
            return route.continue_()

        self.context.route("**/*", _route_handler)

        # Создаем одну вкладку и выставляем короткие таймауты (повторно используем её)
        self.page = self.context.new_page()
        self.context.set_default_timeout(12000)
        self.context.set_default_navigation_timeout(20000)
        self.page.set_default_timeout(12000)
        self.page.set_default_navigation_timeout(20000)

    def parse_coin(self, coin_name):
        """Парсит одну монету"""
        page = None
        try:
            if self.context is None:
                self._create_context()

            # Определяем symbol и base_name в зависимости от суффикса .P
            if coin_name.upper().endswith('.P'):
                # Убираем .P
                base_name = coin_name.upper()[:-2]
                # Если base_name заканчивается на USDT, убираем USDT
                if base_name.endswith('USDT'):
                    base_name = base_name[:-4]
                symbol = coin_name.upper()
            else:
                if coin_name.upper().endswith('USDT'):
                    symbol = coin_name.upper()
                    base_name = coin_name.upper()[:-4]  # Убираем USDT для хранения в БД
                else:
                    symbol = f"{coin_name.upper()}USDT"
                    base_name = coin_name.upper()

            logger.info(f"Начало парсинга монеты: {symbol}")

            # Используем одну и ту же страницу
            page = self.page

            url = f"https://ru.tradingview.com/symbols/{symbol}/markets/"
            logger.info(f"Переход по URL: {url}")

            try:
                page.goto(url, timeout=25000, wait_until="domcontentloaded")
                logger.info("Страница загружена")
            except PlaywrightTimeoutError:
                logger.warning("Таймаут при загрузке страницы, продолжаем")

            # Проверяем существование монеты
            try:
                page.wait_for_selector("h1", timeout=6000)
                not_found = page.query_selector("text=К сожалению, такой тикер не найден")
                if not_found:
                    logger.warning(f"Монета не найдена: {symbol}")
                    return {
                        'name': base_name,
                        'spot': [],
                        'futures': []
                    }
            except PlaywrightTimeoutError:
                logger.warning("Таймаут при проверке существования монеты")

            # Кликаем кнопку Markets
            logger.info("Попытка открыть меню Markets")
            menu_opened = self._open_markets_menu(page)

            if not menu_opened:
                logger.warning("Не удалось открыть меню Markets, используем резервный метод")
                return self._parse_without_menu(page, base_name)

            # Собираем данные из меню
            logger.info("Сбор данных из меню")
            spot_exchanges, futures_exchanges = self._parse_markets_menu(page)

            # Дополнительный сбор из таблицы
            logger.info("Дополнительный сбор из основной таблицы")
            main_table_exchanges = self._collect_main_table_exchanges(page)

            # Добавляем все биржи из основной таблицы в спотовый список
            for exchange in main_table_exchanges:
                if exchange and exchange not in spot_exchanges:
                    spot_exchanges.append(exchange)
                    logger.info(f"Добавлена пропущенная биржа в спот: {exchange} (основная таблица)")

            # Удаляем дубликаты
            spot_exchanges = list(set(spot_exchanges))
            futures_exchanges = list(set(futures_exchanges))

            # Фильтруем пустые значения
            spot_exchanges = [e for e in spot_exchanges if e]
            futures_exchanges = [e for e in futures_exchanges if e]

            logger.info(f"Успешно спарсено: {len(spot_exchanges)} спотовых, {len(futures_exchanges)} фьючерсных бирж")

            return {
                'name': base_name,  # Сохраняем базовое название без USDT и без .P
                'spot': spot_exchanges,
                'futures': futures_exchanges
            }

        except Exception as e:
            logger.error(f"Ошибка парсинга {coin_name}: {str(e)}", exc_info=True)
            return {
                'name': base_name if 'base_name' in locals() else coin_name.upper(),
                'spot': [],
                'futures': []
            }
        finally:
            # страницу не закрываем — переиспользуем; контекст/браузер закрываются в close()
            pass

    def parse_coins_batch(self, coin_names):
        """Парсит несколько монет используя один контекст"""
        results = {}
        for coin_name in coin_names:
            try:
                result = self.parse_coin(coin_name)
                results[coin_name] = result
            except Exception as e:
                results[coin_name] = {"error": str(e), "coin": coin_name}
        return results

    def _open_markets_menu(self, page):
        """Пытается открыть меню Markets различными способами"""
        try:
            # Сначала ищем кнопку Markets по тексту (русская версия)
            markets_btn = page.query_selector("button:has-text('Маркеты'), button:has-text('Markets')")

            if markets_btn:
                # Кликаем через JavaScript
                page.evaluate('(btn) => { btn.click(); }', markets_btn)

                # Ждем быстрое появление
                try:
                    page.wait_for_selector("div[data-name='menu-inner']", timeout=900)
                    return True
                except:
                    pass

                time.sleep(0.15)

            # Если не нашли по тексту, ищем по data-name
            markets_btn = page.query_selector("button[data-name='markets']")
            if markets_btn:
                box = markets_btn.bounding_box()
                if box:
                    page.mouse.click(box['x'] + box['width'] / 2, box['y'] + box['height'] / 2)
                    try:
                        page.wait_for_selector("div[data-name='menu-inner']", timeout=900)
                        return True
                    except:
                        pass
                    time.sleep(0.15)

            # Прямой вызов события
            page.evaluate("""
                () => {
                    const btn = document.querySelector("button[data-name='markets']");
                    if (btn) {
                        const event = new MouseEvent('click', { bubbles: true, cancelable: true, view: window });
                        btn.dispatchEvent(event);
                    }
                }
            """)

            try:
                page.wait_for_selector("div[data-name='menu-inner']", timeout=900)
                return True
            except:
                return False

        except Exception as e:
            logger.error(f"Ошибка при открытии меню Markets: {str(e)}")
            return False

    def _parse_markets_menu(self, page):
        """Парсит биржи из выпадающего меню Markets"""
        spot_exchanges = []
        futures_exchanges = []

        try:
            # Ждем появления меню
            page.wait_for_selector("div[data-name='menu-inner']", timeout=5000)

            # Находим все строки в меню
            rows = page.query_selector_all("div[data-name='menu-inner'] tr")
            logger.info(f"Найдено {len(rows)} строк в меню")

            for row in rows:
                # Пропускаем заголовки
                if row.query_selector("th"):
                    continue

                # Получаем текст всей строки
                row_text = row.inner_text().lower()

                # Получаем название биржи
                exchange = ""
                exchange_cell = row.query_selector("td:nth-child(2)")
                if exchange_cell:
                    raw = exchange_cell.inner_text()
                    exchange = _normalize_exchange_name(raw)

                if not exchange:
                    continue

                # Определяем тип торговли по тексту строки
                if "спот" in row_text:
                    spot_exchanges.append(exchange)
                    logger.info(f"Добавлена спотовая биржа: {exchange}")
                elif "своп" in row_text:
                    futures_exchanges.append(exchange)
                    logger.info(f"Добавлена фьючерсная биржа: {exchange}")
                else:
                    # Если не можем определить по тексту, используем резервную логику
                    instrument = ""
                    instrument_cell = row.query_selector("td:nth-child(1)")
                    if instrument_cell:
                        instrument = instrument_cell.inner_text().strip().lower()

                    if ".p" in instrument or " perpetual" in instrument:
                        futures_exchanges.append(exchange)
                        logger.info(f"Добавлена фьючерсная биржа (по инструменту): {exchange}")
                    else:
                        spot_exchanges.append(exchange)
                        logger.info(f"Добавлена спотовая биржа (по умолчанию): {exchange}")

        except PlaywrightTimeoutError:
            logger.warning("Таймаут при парсинге меню Markets")
        except Exception as e:
            logger.error(f"Ошибка парсинга меню: {str(e)}")

        return spot_exchanges, futures_exchanges

    def _parse_without_menu(self, page, coin_name):
        """Резервный метод парсинга без открытия меню"""
        logger.info("Используем резервный метод парсинга")
        spot_exchanges = []
        futures_exchanges = []

        try:
            # Пытаемся получить данные из основной таблицы
            page.wait_for_selector("table", timeout=10000)
            rows = page.query_selector_all("table tbody tr")
            logger.info(f"Найдено {len(rows)} строк в основной таблице")

            for row in rows:
                cells = row.query_selector_all("td")
                if len(cells) < 3:
                    continue

                # Название биржи
                exchange_cell = cells[1]
                exchange = _normalize_exchange_name(exchange_cell.inner_text())

                # Название инструмента
                instrument_cell = cells[0]
                instrument = instrument_cell.inner_text().strip().lower()

                # Тип торговли
                trade_type_cell = cells[2]
                trade_type = trade_type_cell.inner_text().lower()

                # Определяем тип торговли по тексту
                if "спот" in trade_type:
                    spot_exchanges.append(exchange)
                    logger.info(f"Добавлена спотовая биржа: {exchange}")
                elif "своп" in trade_type:
                    futures_exchanges.append(exchange)
                    logger.info(f"Добавлена фьючерсная биржа: {exchange}")
                else:
                    # Если не можем определить по тексту, используем резервную логику
                    if ".p" in instrument or " perpetual" in instrument:
                        futures_exchanges.append(exchange)
                        logger.info(f"Добавлена фьючерсная биржа (по инструменту): {exchange}")
                    else:
                        spot_exchanges.append(exchange)
                        logger.info(f"Добавлена спотовая биржа (по умолчанию): {exchange}")

        except Exception as e:
            logger.error(f"Ошибка в резервном методе: {str(e)}")

        return {
            'name': coin_name.upper(),
            'spot': list(set(spot_exchanges)),
            'futures': list(set(futures_exchanges))
        }

    def _collect_main_table_exchanges(self, page):
        """Собирает биржи из основной таблицы на странице"""
        exchanges = []

        try:
            page.wait_for_selector("table", timeout=5000)
            rows = page.query_selector_all("table tbody tr")

            for row in rows:
                cells = row.query_selector_all("td")
                if len(cells) > 1:
                    exchange_cell = cells[1]
                    exchange_name = _normalize_exchange_name(exchange_cell.inner_text())

                    # Если есть логотип с текстом
                    logo = exchange_cell.query_selector("span.logoWithTextCell-a8VpuDyP")
                    if logo and not exchange_name:
                        exchange_name = _normalize_exchange_name(logo.inner_text())

                    # Также проверяем ссылки
                    link = exchange_cell.query_selector("a")
                    if link:
                        exchange_name = _normalize_exchange_name(link.inner_text())

                    if exchange_name:
                        exchanges.append(exchange_name)
                        logger.info(f"Добавлена биржа из основной таблицы: {exchange_name}")
        except Exception as e:
            logger.error(f"Ошибка при сборе данных из основной таблицы: {str(e)}")

        return exchanges

    def close(self):
        """Закрывает парсер"""
        if self._closed:
            return

        try:
            if self.page:
                self.page.close()
        except:
            pass

        try:
            if self.context:
                self.context.close()
        except:
            pass

        with TradingViewParser._browser_lock:
            TradingViewParser._instance_count -= 1

            # Закрываем браузер только когда все экземпляры закрыты
            if TradingViewParser._instance_count <= 0 and TradingViewParser._browser:
                try:
                    TradingViewParser._browser.close()
                    TradingViewParser._browser = None
                except:
                    pass

                if TradingViewParser._playwright:
                    try:
                        TradingViewParser._playwright.stop()
                        TradingViewParser._playwright = None
                    except:
                        pass

        self._closed = True

    def __del__(self):
        if not self._closed:
            self.close()


# Функция для запуска в отдельном процессе
def parse_coin_in_process(coin_name, headless=True):
    try:
        parser = TradingViewParser(headless=headless)
        result = parser.parse_coin(coin_name)
        parser.close()
        return result
    except Exception as e:
        return {"error": str(e), "coin": coin_name}


# Функция для обработки пакета монет в одном процессе
def parse_coins_batch_process(coin_names, headless=True):
    """Парсит пакет монет в одном процессе с одним браузером"""
    results = {}
    parser = TradingViewParser(headless=headless)

    try:
        for coin_name in coin_names:
            try:
                result = parser.parse_coin(coin_name)
                results[coin_name] = result
            except Exception as e:
                results[coin_name] = {"error": str(e), "coin": coin_name}
    finally:
        parser.close()

    return results
