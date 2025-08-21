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


class TradingViewParser:
    _instances = {}
    _lock = threading.Lock()

    def __new__(cls, headless=True, instance_id="default"):
        with cls._lock:
            if instance_id not in cls._instances:
                instance = super(TradingViewParser, cls).__new__(cls)
                cls._instances[instance_id] = instance
                instance._initialized = False
            return cls._instances[instance_id]

    def __init__(self, headless=True, instance_id="default"):
        if self._initialized:
            return

        self.headless = headless
        self.instance_id = instance_id
        self.playwright = None
        self.browser = None
        self.context = None
        self.page = None
        self._closed = False
        self._initialized = True
        self._request_queue = Queue()
        self._result_queue = Queue()
        self._worker_thread = None

        logger.info(f"Инициализация парсера (ID: {instance_id})")
        self._start_worker()

    def _start_worker(self):
        """Запускаем фоновый поток для обработки запросов"""
        self._worker_thread = threading.Thread(target=self._process_requests, daemon=True)
        self._worker_thread.start()

    def _process_requests(self):
        """Обрабатывает запросы в фоновом режиме"""
        try:
            self.playwright = sync_playwright().start()

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
                ],
                "timeout": 60000
            }

            self.browser = self.playwright.chromium.launch(**launch_options)
            logger.info("Браузер успешно запущен")

            self.context = self.browser.new_context(
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
            logger.info("Контекст браузера создан")

            self.context.add_init_script("""
                delete navigator.__proto__.webdriver;
                Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
                Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3, 4, 5]});
                Object.defineProperty(navigator, 'languages', {get: () => ['ru-RU', 'ru']};
            """)

            # Обрабатываем запросы в бесконечном цикле
            while True:
                coin_name = self._request_queue.get()
                if coin_name is None:  # Сигнал остановки
                    break

                try:
                    result = self._parse_coin_internal(coin_name)
                    self._result_queue.put((coin_name, result))
                except Exception as e:
                    self._result_queue.put((coin_name, {"error": str(e), "coin": coin_name}))

        except Exception as e:
            logger.error(f"Ошибка в фоновом процессе: {str(e)}")
            self._result_queue.put(("ERROR", {"error": str(e)}))
        finally:
            self._cleanup()

    def _parse_coin_internal(self, coin_name):
        """Внутренний метод для парсинга одной монеты"""
        page = None
        try:
            symbol = f"{coin_name.upper()}USDT"
            logger.info(f"Начало парсинга монеты: {symbol}")

            # Создаем новую страницу для каждого запроса
            page = self.context.new_page()
            page.set_default_timeout(30000)

            url = f"https://ru.tradingview.com/symbols/{symbol}/markets/"
            logger.info(f"Переход по URL: {url}")

            try:
                page.goto(url, timeout=60000, wait_until="domcontentloaded")
                logger.info("Страница загружена")
            except PlaywrightTimeoutError:
                logger.warning("Таймаут при загрузке страницы, продолжаем")

            # Проверяем существование монеты
            try:
                page.wait_for_selector("h1", timeout=10000)
                not_found = page.query_selector("text=К сожалению, такой тикер не найден")
                if not_found:
                    logger.warning(f"Монета не найдена: {symbol}")
                    return {
                        'name': coin_name.upper(),
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
                return self._parse_without_menu(page, coin_name)

            # Собираем данные из меню
            logger.info("Сбор данных из меню")
            spot_exchanges, futures_exchanges = self._parse_markets_menu(page)

            # Дополнительный сбор из таблицы - ВОССТАНАВЛИВАЕМ ИСХОДНУЮ ЛОГИКУ
            logger.info("Дополнительный сбор из основной таблицы")
            main_table_exchanges = self._collect_main_table_exchanges(page)

            # Добавляем пропущенные биржи - ВОССТАНАВЛИВАЕМ ИСХОДНУЮ ЛОГИКУ
            for exchange in main_table_exchanges:
                if exchange and exchange not in spot_exchanges and exchange not in futures_exchanges:
                    spot_exchanges.append(exchange)
                    logger.info(f"Добавлена пропущенная биржа: {exchange} (основная таблица)")

            # Удаляем дубликаты
            spot_exchanges = list(set(spot_exchanges))
            futures_exchanges = list(set(futures_exchanges))

            # Фильтруем пустые значения
            spot_exchanges = [e for e in spot_exchanges if e]
            futures_exchanges = [e for e in futures_exchanges if e]

            logger.info(f"Успешно спарсено: {len(spot_exchanges)} спотовых, {len(futures_exchanges)} фьючерсных бирж")

            return {
                'name': coin_name.upper(),
                'spot': spot_exchanges,
                'futures': futures_exchanges
            }

        except Exception as e:
            logger.error(f"Ошибка парсинга {coin_name}: {str(e)}", exc_info=True)
            try:
                if page:
                    page.screenshot(path=f"error_{coin_name}.png")
                    logger.info(f"Скриншот ошибки сохранен как error_{coin_name}.png")
            except:
                pass
            return {
                'name': coin_name.upper(),
                'spot': [],
                'futures': []
            }
        finally:
            if page:
                try:
                    page.close()
                except:
                    pass

    def parse_coin(self, coin_name):
        """Добавляет запрос в очередь и возвращает результат"""
        self._request_queue.put(coin_name)
        return self._result_queue.get()

    def parse_coins_batch(self, coin_names):
        """Парсит несколько монет и возвращает результаты"""
        results = {}
        for coin_name in coin_names:
            self._request_queue.put(coin_name)

        for _ in range(len(coin_names)):
            coin_name, result = self._result_queue.get()
            results[coin_name] = result

        return results

    def _open_markets_menu(self, page):
        """Пытается открыть меню Markets различными способами"""
        try:
            # Способ 1: Клик через JavaScript
            clicked = page.evaluate('''() => {
                const btn = document.querySelector("button[data-name='markets']");
                if (btn && !btn.disabled) {
                    btn.click();
                    return true;
                }
                return false;
            }''')

            time.sleep(1)  # Краткая пауза

            # Проверяем успешность
            if page.query_selector("div[data-name='menu-inner']"):
                return True

            # Способ 2: Клик через координаты
            btn = page.query_selector("button[data-name='markets']")
            if btn:
                box = btn.bounding_box()
                if box:
                    page.mouse.click(box['x'] + box['width'] / 2, box['y'] + box['height'] / 2)
                    time.sleep(1)
                    if page.query_selector("div[data-name='menu-inner']"):
                        return True

            # Способ 3: Прямой вызов события
            page.evaluate('''() => {
                const btn = document.querySelector("button[data-name='markets']");
                if (btn) {
                    const event = new MouseEvent('click', {
                        bubbles: true,
                        cancelable: true,
                        view: window
                    });
                    btn.dispatchEvent(event);
                }
            }''')

            time.sleep(1.5)
            return bool(page.query_selector("div[data-name='menu-inner']"))

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
                    exchange = exchange_cell.inner_text().split('\n')[-1].strip()

                # Определяем тип торговли
                if not exchange:
                    continue

                if "спот" in row_text or "spot" in row_text:
                    spot_exchanges.append(exchange)
                elif "фьючерс" in row_text or "futures" in row_text or "своп" in row_text or "swap" in row_text:
                    futures_exchanges.append(exchange)
                elif ".p" in row_text or " perpetual" in row_text or "фьючи" in row_text or "fut" in row_text:
                    futures_exchanges.append(exchange)
                elif "деривативы" in row_text or "derivatives" in row_text:
                    futures_exchanges.append(exchange)
                else:
                    spot_exchanges.append(exchange)

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
                exchange = exchange_cell.inner_text().strip()

                # Тип торговли
                trade_type_cell = cells[2]
                trade_type = trade_type_cell.inner_text().lower()

                if "спот" in trade_type or "spot" in trade_type:
                    spot_exchanges.append(exchange)
                elif "фьючерс" in trade_type or "futures" in trade_type:
                    futures_exchanges.append(exchange)
                elif "перпет" in trade_type or "perp" in trade_type:
                    futures_exchanges.append(exchange)
                else:
                    spot_exchanges.append(exchange)

        except Exception as e:
            logger.error(f"Ошибка в резервном методе: {str(e)}")

        return {
            'name': coin_name.upper(),
            'spot': list(set(spot_exchanges)),
            'futures': list(set(futures_exchanges))
        }

    def _collect_main_table_exchanges(self, page):
        """Собирает биржи из основной таблицы на странице - ВОССТАНАВЛИВАЕМ ИСХОДНУЮ ЛОГИКУ"""
        exchanges = []

        try:
            page.wait_for_selector("table", timeout=5000)
            rows = page.query_selector_all("table tbody tr")

            for row in rows:
                cells = row.query_selector_all("td")
                if len(cells) > 1:
                    exchange_cell = cells[1]
                    exchange_name = exchange_cell.inner_text().strip()

                    # Если есть логотип с текстом
                    logo = exchange_cell.query_selector("span.logoWithTextCell-a8VpuDyP")
                    if logo:
                        exchange_name = logo.inner_text().strip()

                    if exchange_name:
                        exchanges.append(exchange_name)
        except:
            pass

        return exchanges

    def _cleanup(self):
        """Внутренняя очистка ресурсов"""
        logger.info("Очистка ресурсов парсера")

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

        try:
            if self.browser:
                self.browser.close()
        except:
            pass

        try:
            if self.playwright:
                self.playwright.stop()
        except:
            pass

        self._closed = True

    def close(self):
        """Публичное закрытие парсера"""
        if self._closed:
            return

        # Отправляем сигнал остановки воркеру
        self._request_queue.put(None)

        try:
            if self._worker_thread and self._worker_thread.is_alive():
                self._worker_thread.join(timeout=5)
        except:
            pass

        self._cleanup()
        logger.info("Ресурсы парсера полностью закрыты")

    def reset(self):
        """Сброс парсера для повторного использования"""
        self.close()
        # Удаляем instance из словаря, чтобы можно было создать новый
        with self._lock:
            if self.instance_id in TradingViewParser._instances:
                del TradingViewParser._instances[self.instance_id]
        self._initialized = False

    def __del__(self):
        if not self._closed:
            self.close()


# Функция для запуска в отдельном процессе (сохраняем для обратной совместимости)
def parse_coin_in_process(coin_name, headless=True):
    try:
        # Создаем уникальный ID для каждого процесса
        process_id = f"process_{os.getpid()}_{threading.get_ident()}"
        parser = TradingViewParser(headless=headless, instance_id=process_id)
        result = parser.parse_coin(coin_name)
        parser.close()
        return result
    except Exception as e:
        return {"error": str(e), "coin": coin_name}