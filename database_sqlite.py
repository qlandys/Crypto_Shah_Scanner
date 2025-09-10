# database_sqlite.py
import os
import shutil
import sqlite3
from dataclasses import dataclass
from typing import List

@dataclass
class Coin:
    name: str
    spot_exchanges: str
    futures_exchanges: str
    favorite: bool = False
    note: str = ""  # <— примечание

class Database:
    PROFILES_DIR = "profiles"

    def __init__(self, profile_name='default'):
        self.profile_name = profile_name
        os.makedirs(self.PROFILES_DIR, exist_ok=True)
        self.filename = os.path.join(self.PROFILES_DIR, f"{profile_name}.db")
        self._conn = sqlite3.connect(self.filename, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL;")
        self._conn.execute("PRAGMA synchronous=NORMAL;")
        self._conn.execute("PRAGMA temp_store=MEMORY;")
        self._conn.execute("PRAGMA mmap_size=134217728;")  # 128MB mmap
        self._ensure_schema()

        # миграция из json если раньше был json файл
        legacy_json = os.path.join(self.PROFILES_DIR, f"{profile_name}.json")
        if os.path.exists(legacy_json) and self._is_table_empty():
            try:
                import json
                with open(legacy_json, "r", encoding="utf-8") as f:
                    data = json.load(f)
                for item in data:
                    self.save_coin(
                        item.get("name", ""),
                        item.get("spot_exchanges", ""),
                        item.get("futures_exchanges", "")
                    )
                    fav = bool(item.get("favorite", False))
                    if fav:
                        self.set_favorite(item.get("name",""), True)
                    note = item.get("note", "")
                    if note:
                        self.set_note(item.get("name",""), note)
            except Exception:
                pass

    def _ensure_schema(self):
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS coins (
                name TEXT PRIMARY KEY,
                spot TEXT NOT NULL DEFAULT '',
                futures TEXT NOT NULL DEFAULT '',
                favorite INTEGER NOT NULL DEFAULT 0,
                note TEXT NOT NULL DEFAULT ''
            )
        """)
        self._conn.execute("CREATE INDEX IF NOT EXISTS idx_fav ON coins(favorite);")

        # миграция: если старый столбец note отсутствует — добавим
        try:
            cols = {row[1] for row in self._conn.execute("PRAGMA table_info(coins)")}
            if "note" not in cols:
                self._conn.execute("ALTER TABLE coins ADD COLUMN note TEXT NOT NULL DEFAULT ''")
        except Exception:
            pass

        self._conn.commit()

    def _is_table_empty(self) -> bool:
        cur = self._conn.execute("SELECT 1 FROM coins LIMIT 1")
        return cur.fetchone() is None

    def load(self):
        pass

    def save(self):
        pass

    def close(self):
        try:
            self._conn.close()
        except Exception:
            pass

    # Жёстко закрыть соединение (для Windows, чтобы отпустить файл)
    def dispose(self):
        try:
            self._conn.commit()
        except Exception:
            pass
        try:
            self._conn.close()
        except Exception:
            pass
        self._conn = None

    def _unlink_wal_files(self, base_path: str):
        # удаляем хвосты WAL/SHM, если остались
        variants = []
        if base_path.endswith(".db"):
            stem = base_path[:-3]
            variants.extend([stem + "-wal", stem + "-shm"])
            variants.extend([base_path + "-wal", base_path + "-shm"])
            variants.extend([base_path + ".wal", base_path + ".shm"])
        else:
            variants.extend([base_path + "-wal", base_path + "-shm"])
            variants.extend([base_path + ".wal", base_path + ".shm"])
        for p in variants:
            try:
                if os.path.exists(p):
                    os.remove(p)
            except Exception:
                pass

    def save_coin(self, name: str, spot_exchanges: str, futures_exchanges: str):
        if not name:
            return
        self._conn.execute("""
            INSERT INTO coins(name, spot, futures)
            VALUES(?, ?, ?)
            ON CONFLICT(name) DO UPDATE SET
                spot=excluded.spot,
                futures=excluded.futures
        """, (name, spot_exchanges or "", futures_exchanges or ""))
        self._conn.commit()

    def set_favorite(self, name: str, value: bool):
        self._conn.execute("UPDATE coins SET favorite=? WHERE name=?", (1 if value else 0, name))
        self._conn.commit()

    def set_note(self, name: str, text: str):
        self._conn.execute("UPDATE coins SET note=? WHERE name=?", (text or "", name))
        self._conn.commit()

    def get_note(self, name: str) -> str:
        cur = self._conn.execute("SELECT note FROM coins WHERE name=?", (name,))
        row = cur.fetchone()
        return row[0] if row else ""

    def delete_coin(self, name: str) -> bool:
        cur = self._conn.execute("DELETE FROM coins WHERE name=?", (name,))
        self._conn.commit()
        return cur.rowcount > 0

    def search_coins(self) -> List[Coin]:
        cur = self._conn.execute("SELECT name, spot, futures, favorite, note FROM coins")
        rows = cur.fetchall()
        return [Coin(name=r[0], spot_exchanges=r[1], futures_exchanges=r[2],
                     favorite=bool(r[3]), note=r[4] or "") for r in rows]

    def reload_from_file(self):
        pass

    def delete_profile(self) -> bool:
        self.dispose()  # полностью закрыть соединение
        ok = False
        if os.path.exists(self.filename):
            try:
                self._unlink_wal_files(self.filename)
                os.remove(self.filename)
                ok = True
            except PermissionError:
                import time
                time.sleep(0.2)
                self._unlink_wal_files(self.filename)
                os.remove(self.filename)
                ok = True
        return ok

    def copy_profile(self, new_profile_name: str):
        new_filename = os.path.join(self.PROFILES_DIR, f"{new_profile_name}.db")
        self._conn.commit()
        self._conn.close()
        shutil.copyfile(self.filename, new_filename)
        # Открываем текущий обратно
        self._conn = sqlite3.connect(self.filename, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL;")
        self._conn.execute("PRAGMA synchronous=NORMAL;")
        self._conn.execute("PRAGMA temp_store=MEMORY;")
        return Database(new_profile_name)

    def rename_profile(self, new_name: str):
        old_path = self.filename
        new_path = os.path.join(os.path.dirname(old_path), f"{new_name}.db")
        self.dispose()
        try:
            if os.path.exists(old_path):
                self._unlink_wal_files(old_path)
                os.replace(old_path, new_path)
            self.filename = new_path
            self.profile_name = new_name
            self._conn = sqlite3.connect(self.filename, check_same_thread=False)
            self._conn.execute("PRAGMA journal_mode=WAL;")
            self._conn.execute("PRAGMA synchronous=NORMAL;")
            self._conn.execute("PRAGMA temp_store=MEMORY;")
            return self
        except Exception as e:
            raise Exception(f"Не удалось переименовать профиль: {str(e)}")

    @classmethod
    def list_profiles(cls):
        os.makedirs(cls.PROFILES_DIR, exist_ok=True)
        profiles = []
        for file in os.listdir(cls.PROFILES_DIR):
            if file.endswith(".db"):
                profiles.append(file[:-3])
            elif file.endswith(".json"):
                name = file[:-5]
                if not os.path.exists(os.path.join(cls.PROFILES_DIR, f"{name}.db")):
                    profiles.append(name)
        return sorted(set(profiles))
