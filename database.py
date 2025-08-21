import json
import os
from dataclasses import dataclass
import shutil


@dataclass
class Coin:
    name: str
    spot_exchanges: str
    futures_exchanges: str


class Database:
    PROFILES_DIR = "profiles"

    def __init__(self, profile_name='default'):
        self.profile_name = profile_name
        self.filename = f"{self.PROFILES_DIR}/{profile_name}.json"
        self.coins = []

        # Создаем директорию профилей если нужно
        os.makedirs(self.PROFILES_DIR, exist_ok=True)
        self.load()

    def load(self):
        """Загружает данные из JSON файла"""
        if os.path.exists(self.filename):
            try:
                with open(self.filename, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    self.coins = [Coin(**item) for item in data]
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
                'futures_exchanges': coin.futures_exchanges
            } for coin in self.coins]
            json.dump(data, f, indent=2, ensure_ascii=False)

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
        self.save()

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