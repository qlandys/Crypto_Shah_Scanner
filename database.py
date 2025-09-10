import json
import os
from dataclasses import dataclass
import shutil
import threading          # <— добавили



@dataclass
class Coin:
    name: str
    spot_exchanges: str
    futures_exchanges: str
    favorite: bool = False  # <— добавили


class Database:
    PROFILES_DIR = "profiles"

    def __init__(self, profile_name='default'):
        self.profile_name = profile_name
        self.filename = f"{self.PROFILES_DIR}/{profile_name}.json"
        self.coins = []
        self._save_timer = None  # <— добавили
        self._save_lock = threading.Lock()
        # Создаем директорию профилей если нужно
        os.makedirs(self.PROFILES_DIR, exist_ok=True)
        self.load()

    def load(self):
        """Загружает данные из JSON файла"""
        if os.path.exists(self.filename):
            try:
                with open(self.filename, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    self.coins = [Coin(
                        name=item.get('name', ''),
                        spot_exchanges=item.get('spot_exchanges', ''),
                        futures_exchanges=item.get('futures_exchanges', ''),
                        favorite=item.get('favorite', False)  # <— дефолт
                    ) for item in data]
            except (json.JSONDecodeError, FileNotFoundError):
                self.coins = []
        else:
            self.coins = []

    def save(self):
        """Сохраняет данные в JSON файл"""
        with open(self.filename, 'w', encoding='utf-8') as f:
            data = [{
                'name': coin.name,
                'spot_exchanges': coin.spot_exchanges,
                'futures_exchanges': coin.futures_exchanges,
                'favorite': getattr(coin, 'favorite', False)  # <— сохраняем
            } for coin in self.coins]
            json.dump(data, f, indent=2, ensure_ascii=False)

    def _schedule_save(self, delay: float = 0.4):
        """Поставить сохранение на таймер (дебаунс) — чтобы не блокировать UI на каждый чих."""

        def _do_save():
            with self._save_lock:
                try:
                    # атомарная запись через временный файл
                    tmp = f"{self.filename}.tmp"
                    data = [{
                        'name': c.name,
                        'spot_exchanges': c.spot_exchanges,
                        'futures_exchanges': c.futures_exchanges,
                        'favorite': getattr(c, 'favorite', False)
                    } for c in self.coins]
                    with open(tmp, 'w', encoding='utf-8') as f:
                        json.dump(data, f, indent=2, ensure_ascii=False)
                    os.replace(tmp, self.filename)  # атомарно
                finally:
                    # снимаем ссылку на таймер
                    self._save_timer = None

        # перезапускаем таймер, если уже был
        if self._save_timer and self._save_timer.is_alive():
            self._save_timer.cancel()
        self._save_timer = threading.Timer(delay, _do_save)
        self._save_timer.daemon = True
        self._save_timer.start()

    def close(self):
        """Закрывает соединение с базой данных"""
        # Для JSON базы данных просто очищаем данные
        self.coins = []

    def save_coin(self, name, spot_exchanges, futures_exchanges):
        """Сохраняет или обновляет данные о монете"""
        # Ищем монету в базе
        existing_coin = None
        for coin in self.coins:
            if coin.name == name:
                existing_coin = coin
                break

        if existing_coin:
            # Обновляем существующую монету
            existing_coin.spot_exchanges = spot_exchanges
            existing_coin.futures_exchanges = futures_exchanges
        else:
            # Добавляем новую монету
            self.coins.append(Coin(name, spot_exchanges, futures_exchanges))

        # Сохраняем изменения в файл
        self._schedule_save()

    def set_favorite(self, name: str, value: bool):
        """Установить/снять признак избранного у монеты и сохранить файл"""
        for coin in self.coins:
            if coin.name == name:
                coin.favorite = bool(value)
                self._schedule_save()
                return True
        return False

    def delete_coin(self, name: str):
        """Удалить монету из базы навсегда"""
        before = len(self.coins)
        self.coins = [c for c in self.coins if c.name != name]
        if len(self.coins) != before:
            self._schedule_save()
            return True
        return False

    def search_coins(self):
        """Возвращает все монеты из базы"""
        return self.coins

    def reload_from_file(self):
        """Перезагружает данные из файла"""
        self.load()

    def delete_profile(self):
        """Удаляет файл профиля"""
        try:
            if os.path.exists(self.filename):
                os.remove(self.filename)
                self.coins = []
                return True
            return False
        except Exception as e:
            raise Exception(f"Не удалось удалить профиль: {str(e)}")

    def copy_profile(self, new_profile_name):
        """Копирует текущий профиль в новый"""
        new_filename = f"{self.PROFILES_DIR}/{new_profile_name}.json"
        try:
            if os.path.exists(self.filename):
                shutil.copyfile(self.filename, new_filename)
            return Database(new_profile_name)
        except Exception as e:
            raise Exception(f"Не удалось скопировать профиль: {str(e)}")

    def rename_profile(self, new_name):
        """Переименовать профиль"""
        if not self.filename:
            return None

        old_path = self.filename
        new_path = os.path.join(os.path.dirname(old_path), f"{new_name}.json")

        try:
            # Переименовываем файл
            if os.path.exists(old_path):
                os.rename(old_path, new_path)
                self.filename = new_path
                self.profile_name = new_name
                return self
        except Exception as e:
            raise Exception(f"Не удалось переименовать профиль: {str(e)}")

        return None

    @classmethod
    def list_profiles(cls):
        """Возвращает список всех профилей"""
        os.makedirs(cls.PROFILES_DIR, exist_ok=True)
        profiles = []
        for file in os.listdir(cls.PROFILES_DIR):
            if file.endswith(".json"):
                profiles.append(file[:-5])
        return sorted(profiles)