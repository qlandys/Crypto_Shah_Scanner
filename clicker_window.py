import pyautogui
import time
import threading
import os
import json
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QTextEdit, QDialog,
    QDialogButtonBox, QFrame, QGroupBox, QFormLayout, QDoubleSpinBox, QLineEdit,
    QFileDialog
)
from PyQt5.QtCore import Qt, pyqtSignal, QObject, QSize, QUrl
from PyQt5.QtGui import QFont, QIcon
from PyQt5.QtMultimedia import QMediaPlayer, QMediaContent, QSoundEffect
from pynput import mouse, keyboard


# --------------------- signals ---------------------
class ClickerSignals(QObject):
    log_signal = pyqtSignal(str)
    update_indicator_signal = pyqtSignal(bool)


# --------------------- config ----------------------
class Config:
    def __init__(self):
        self.config_file = "clicker_config.json"
        self.default = {
            "bindings": {
                "toggle_left": "",
                "toggle_right": "",
                "faster_click": "right",
                "slower_click": "left",
                "faster_space": "down",
                "slower_space": "up",
            },
            "step": 0.2,
            "sound_enabled": True,
            # новые поля: пользовательские WAV
            "start_wav_path": "",   # абсолютный или относительный путь
            "stop_wav_path": ""
        }
        self.load()

    def load(self):
        self.bindings = self.default["bindings"].copy()
        self.step = self.default["step"]
        self.sound_enabled = bool(self.default["sound_enabled"])
        self.start_wav_path = self.default["start_wav_path"]
        self.stop_wav_path = self.default["stop_wav_path"]

        if os.path.exists(self.config_file):
            try:
                with open(self.config_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if "bindings" in data and isinstance(data["bindings"], dict):
                    self.bindings.update(data["bindings"])
                if "step" in data:
                    self.step = float(data["step"])
                if "sound_enabled" in data:
                    self.sound_enabled = bool(data["sound_enabled"])
                if "start_wav_path" in data:
                    self.start_wav_path = str(data["start_wav_path"] or "")
                if "stop_wav_path" in data:
                    self.stop_wav_path = str(data["stop_wav_path"] or "")
            except Exception:
                pass

    def save(self):
        with open(self.config_file, "w", encoding="utf-8") as f:
            json.dump({
                "bindings": self.bindings,
                "step": self.step,
                "sound_enabled": self.sound_enabled,
                "start_wav_path": self.start_wav_path,
                "stop_wav_path": self.stop_wav_path,
            }, f, indent=4)

    def get_binding(self, action: str) -> str:
        return self.bindings.get(action, "")

    def set_binding(self, action: str, value: str):
        self.bindings[action] = value or ""
        self.save()

    def get_step(self) -> float:
        try:
            return float(self.step)
        except Exception:
            return 0.2

    def set_step(self, value: float):
        self.step = float(value)
        self.save()

    def is_sound_enabled(self) -> bool:
        return bool(self.sound_enabled)

    def set_sound_enabled(self, value: bool):
        self.sound_enabled = bool(value)
        self.save()

    # --- пути к wav ---
    def get_wav_path(self, kind: str) -> str:
        if kind == "start":
            return self.start_wav_path or ""
        if kind == "stop":
            return self.stop_wav_path or ""
        return ""

    def set_wav_path(self, kind: str, path: str):
        if kind == "start":
            self.start_wav_path = path or ""
        elif kind == "stop":
            self.stop_wav_path = path or ""
        self.save()


# --------------------- helpers ----------------------
def _find_icon(base_no_ext: str) -> QIcon:
    for ext in (".png", ".ico", ".svg"):
        p = base_no_ext + ext
        if os.path.exists(p):
            return QIcon(p)
    return QIcon()

def _abs(path):
    return os.path.abspath(path)


# --------------------- main window -----------------
class ClickerWindow(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.signals = ClickerSignals()
        self.signals.log_signal.connect(self.add_log)
        self.signals.update_indicator_signal.connect(self.update_indicator_status)

        self.config = Config()

        # текущие задержки
        self.click_delay = 0.3   # ожидание после клика перед пробелом
        self.space_delay = 0.3   # ожидание после пробела до следующего клика

        # состояние
        self.left_click_running = False
        self.right_click_running = False
        self._left_stop_event = threading.Event()
        self._right_stop_event = threading.Event()

        self.mouse_listener = None
        self.keyboard_listener = None
        self.settings_window_open = False

        # ---- аудио движки
        self.fx_start = None
        self.fx_stop = None
        self._player_start = None
        self._player_stop = None
        self._winsound_available = False
        self._wav_paths = {}
        self._init_audio()

        # анти-спам звука/тумблера
        self._sound_gate_ms = 120
        self._last_sound_ts = 0.0
        self._toggle_gate_ms = 120
        self._last_toggle_ts = 0.0

        self.init_ui()
        self.apply_theme()
        self.setup_listeners()
        self._refresh_info_label()

    # ---------- UI ----------
    def init_ui(self):
        self.setWindowTitle("Crazy Shah Clicker")
        self.setFixedSize(600, 400)

        layout = QVBoxLayout(self)
        layout.setSpacing(8)
        layout.setContentsMargins(12, 12, 12, 12)

        header_layout = QHBoxLayout()
        title = QLabel("Crazy Shah Clicker")
        title.setFont(QFont("Arial", 16, QFont.Bold))
        title.setStyleSheet("color: #6A5AF9;")
        header_layout.addWidget(title)
        header_layout.addStretch()

        # кнопка звука слева от шестерёнки
        self.sound_btn = QPushButton()
        self.sound_btn.setCheckable(True)
        self.sound_btn.setChecked(self.config.is_sound_enabled())
        self._update_sound_icon()
        self.sound_btn.setFixedSize(28, 28)
        self.sound_btn.setToolTip("Включить/выключить звук")
        self.sound_btn.setStyleSheet("""
            QPushButton { background-color: #444444; border: none; border-radius: 14px; padding: 0; }
            QPushButton:hover { background-color: #555555; }
        """)
        self.sound_btn.clicked.connect(self.toggle_sound)
        self.sound_btn.setFocusPolicy(Qt.NoFocus)
        header_layout.addWidget(self.sound_btn)

        self.settings_btn = QPushButton()
        self.settings_btn.setFixedSize(28, 28)
        self.settings_btn.setToolTip("Настройки")
        if os.path.exists("icons/icon_settings.png"):
            self.settings_btn.setIcon(QIcon("icons/icon_settings.png"))
            self.settings_btn.setIconSize(QSize(20, 20))
        else:
            self.settings_btn.setText("⚙")
        self.settings_btn.setStyleSheet("""
            QPushButton { background-color: #444444; border: none; border-radius: 14px; padding: 0; }
            QPushButton:hover { background-color: #555555; }
        """)
        self.settings_btn.clicked.connect(self.show_settings)
        self.settings_btn.setFocusPolicy(Qt.NoFocus)
        header_layout.addWidget(self.settings_btn)

        layout.addLayout(header_layout)

        self.info_label = QLabel()
        self.info_label.setFont(QFont("Arial", 12, QFont.Bold))
        layout.addWidget(self.info_label)

        self.status_indicator = QFrame()
        self.status_indicator.setFixedHeight(14)
        self.status_indicator.setStyleSheet("background-color: red; border-radius: 7px;")
        layout.addWidget(self.status_indicator)

        self.console = QTextEdit()
        self.console.setReadOnly(True)
        self.console.setFont(QFont("Consolas", 11))
        layout.addWidget(self.console)

        self.add_log("Старт/стоп: Mouse4 → ЛКМ, Mouse5 → ПКМ (плюс назначаемые клавиши).")
        self.add_log("Скорость: →/← — click_delay,  ↓/↑ — space_delay (можно переназначить).")
        self.add_log(f"Шаг: {self.config.get_step():.3f} сек")

    def _refresh_info_label(self):
        self.info_label.setText(
            f"click_delay: {self.click_delay:.3f} сек | space_delay: {self.space_delay:.3f} сек | step: {self.config.get_step():.3f} сек"
        )
        self.info_label.setStyleSheet("color: #DDDDDD; font-weight: bold; font-size: 12px;")

    def apply_theme(self):
        self.setStyleSheet("""
            QWidget { background-color: #1E1E1E; color: #DDDDDD; }
            QTextEdit { background-color: #3A3A3A; color: #DDDDDD; border: 1px solid #555555;
                        border-radius: 4px; font-family: Consolas; font-size: 12px; }
            QLabel { color: #DDDDDD; }
            QPushButton { background-color: #6A5AF9; color: white; border: none; padding: 6px 10px;
                          border-radius: 4px; font-size: 12px; }
            QPushButton:hover { background-color: #5B4AE9; }
            QLineEdit {
                background:#2A2A2A; color:#EEEEEE; border:1px solid #555; border-radius:6px;
                padding:4px 8px; font-size:14px; min-height:28px;
            }
            QDoubleSpinBox {
                background:#2A2A2A; color:#EEEEEE; border:1px solid #555; border-radius:6px;
                padding:4px 8px; font-size:14px; min-height:28px;
            }
        """)

    # ---------- Logs / status ----------
    def add_log(self, message):
        self.console.append(message)
        self.console.verticalScrollBar().setValue(self.console.verticalScrollBar().maximum())

    def update_indicator_status(self, is_active):
        self.status_indicator.setStyleSheet(
            "background-color: green; border-radius: 7px;" if is_active
            else "background-color: red; border-radius: 7px;"
        )

    # ---------- Audio init / play ----------
    def _release_audio(self):
        # безопасно «отпускаем» старые объекты
        try:
            if self.fx_start: self.fx_start.stop()
            if self.fx_stop:  self.fx_stop.stop()
            if self._player_start: self._player_start.stop()
            if self._player_stop:  self._player_stop.stop()
        except Exception:
            pass
        self.fx_start = self.fx_stop = None
        self._player_start = self._player_stop = None
        self._winsound_available = False
        self._wav_paths = {}

    def _init_audio(self):
        self._release_audio()

        # 1) выбираем приоритетный WAV из настроек, иначе дефолт из /sounds
        cfg_start = self.config.get_wav_path("start")
        cfg_stop  = self.config.get_wav_path("stop")

        start_wav = _abs(cfg_start) if cfg_start else _abs(os.path.join("sounds", "start.wav"))
        stop_wav  = _abs(cfg_stop)  if cfg_stop  else _abs(os.path.join("sounds", "stop.wav"))

        start_wav_exists = os.path.exists(start_wav)
        stop_wav_exists  = os.path.exists(stop_wav)

        # 2) На Windows пробуем winsound для мгновенной реакции
        if os.name == "nt":
            try:
                import winsound  # noqa
                self._winsound_available = True
                self._wav_paths = {
                    "start": start_wav if start_wav_exists else "",
                    "stop":  stop_wav  if stop_wav_exists  else ""
                }
            except Exception:
                self._winsound_available = False

        # 3) Если оба WAV есть — готовим QSoundEffect (для не-Windows или как запасной)
        if start_wav_exists and stop_wav_exists and not self._winsound_available:
            try:
                self.fx_start = QSoundEffect(self)
                self.fx_start.setSource(QUrl.fromLocalFile(start_wav))
                self.fx_start.setLoopCount(1)
                self.fx_start.setVolume(1.0)

                self.fx_stop = QSoundEffect(self)
                self.fx_stop.setSource(QUrl.fromLocalFile(stop_wav))
                self.fx_stop.setLoopCount(1)
                self.fx_stop.setVolume(1.0)

                # прогрев
                self.fx_start.setMuted(True); self.fx_start.play(); self.fx_start.stop(); self.fx_start.setMuted(False)
                self.fx_stop.setMuted(True);  self.fx_stop.play();  self.fx_stop.stop();  self.fx_stop.setMuted(False)
            except Exception:
                self.fx_start = self.fx_stop = None

        # 4) Последний вариант — MP3 через QMediaPlayer (если есть файлы в /sounds)
        if not self._winsound_available and not (self.fx_start and self.fx_stop):
            self._player_start = QMediaPlayer(self)
            self._player_stop = QMediaPlayer(self)
            start_mp3 = _abs(os.path.join("sounds", "start.mp3"))
            stop_mp3  = _abs(os.path.join("sounds", "stop.mp3"))
            if os.path.exists(start_mp3):
                self._player_start.setMedia(QMediaContent(QUrl.fromLocalFile(start_mp3)))
                self._player_start.setVolume(100)
            if os.path.exists(stop_mp3):
                self._player_stop.setMedia(QMediaContent(QUrl.fromLocalFile(stop_mp3)))
                self._player_stop.setVolume(100)

    def _play_sound(self, kind: str):
        if not self.config.is_sound_enabled():
            return

        # анти-спам (не чаще, чем раз в _sound_gate_ms)
        now = time.monotonic()
        if (now - self._last_sound_ts) * 1000.0 < self._sound_gate_ms:
            return
        self._last_sound_ts = now

        # Windows fast path (каждый звук отдельно, только если путь есть)
        if self._winsound_available:
            import winsound
            winsound.PlaySound(None, 0)  # сбросить очередь
            path = self._wav_paths.get(kind) or ""
            if path and os.path.exists(path):
                winsound.PlaySound(path, winsound.SND_FILENAME | winsound.SND_ASYNC)
            return

        # QSoundEffect (WAV)
        if self.fx_start and self.fx_stop:
            if kind == "start":
                self.fx_start.stop()
                self.fx_start.play()
            elif kind == "stop":
                self.fx_stop.stop()
                self.fx_stop.play()
            return

        # fallback MP3
        if kind == "start" and self._player_start:
            self._player_start.stop()
            self._player_start.play()
        elif kind == "stop" and self._player_stop:
            self._player_stop.stop()
            self._player_stop.play()

    def toggle_sound(self):
        enabled = self.sound_btn.isChecked()
        self.config.set_sound_enabled(enabled)
        self._update_sound_icon()

    def _update_sound_icon(self):
        if self.sound_btn.isChecked():
            self.sound_btn.setIcon(_find_icon("icons/sound_on"))
            self.sound_btn.setIconSize(QSize(20, 20))
        else:
            self.sound_btn.setIcon(_find_icon("icons/sound_off"))
            self.sound_btn.setIconSize(QSize(20, 20))

    # ---------- Listeners ----------
    def setup_listeners(self):
        self.mouse_listener = mouse.Listener(on_click=self.on_mouse_click)
        self.mouse_listener.start()
        self.keyboard_listener = keyboard.Listener(on_press=self.on_key_press)
        self.keyboard_listener.start()
        self.add_log("Слушатели активированы")

    def _key_to_name(self, key):
        try:
            return key.char
        except AttributeError:
            return str(key).split('.')[-1].lower()

    def on_key_press(self, key):
        if self.settings_window_open:
            return
        key_name = self._key_to_name(key)
        if key_name == 'space':
            return

        step = self.config.get_step()

        # Тогглы режимов
        if self.config.get_binding("toggle_left") and key_name == self.config.get_binding("toggle_left"):
            self.start_left_click()
            return
        if self.config.get_binding("toggle_right") and key_name == self.config.get_binding("toggle_right"):
            self.start_right_click()
            return

        # Регулировка задержек
        if key_name in ("right", "left", "down", "up",
                        self.config.get_binding("faster_click"),
                        self.config.get_binding("slower_click"),
                        self.config.get_binding("faster_space"),
                        self.config.get_binding("slower_space")):

            if key_name == "right" or key_name == self.config.get_binding("faster_click"):
                self.click_delay = max(0.01, self.click_delay - step)
                self.add_log(f"→ click_delay = {self.click_delay:.3f}s")

            elif key_name == "left" or key_name == self.config.get_binding("slower_click"):
                self.click_delay = min(10.0, self.click_delay + step)
                self.add_log(f"← click_delay = {self.click_delay:.3f}s")

            elif key_name == "down" or key_name == self.config.get_binding("faster_space"):
                self.space_delay = max(0.01, self.space_delay - step)
                self.add_log(f"↓ space_delay = {self.space_delay:.3f}s")

            elif key_name == "up" or key_name == self.config.get_binding("slower_space"):
                self.space_delay = min(10.0, self.space_delay + step)
                self.add_log(f"↑ space_delay = {self.space_delay:.3f}s")

            self._refresh_info_label()

    def on_mouse_click(self, x, y, button, pressed):
        if self.settings_window_open:
            return
        if pressed:
            if button == mouse.Button.x1:
                self.signals.log_signal.emit("Mouse4 → ЛКМ-режим")
                self.start_left_click()
            elif button == mouse.Button.x2:
                self.signals.log_signal.emit("Mouse5 → ПКМ-режим")
                self.start_right_click()

    # ---------- worker loops ----------
    def _wait_breakable(self, seconds, stop_event):
        start = time.time()
        while time.time() - start < seconds and not stop_event.is_set():
            time.sleep(0.01)

    def left_click_mode(self):
        self.signals.log_signal.emit("ЛКМ активирован")
        self.signals.update_indicator_signal.emit(True)
        stop = self._left_stop_event
        try:
            while not stop.is_set():
                pyautogui.click()
                self._wait_breakable(self.click_delay, stop)
                pyautogui.press('space')        # ВСЕГДА жмём пробел
                if stop.is_set():
                    break
                self._wait_breakable(self.space_delay, stop)
        except Exception as e:
            self.signals.log_signal.emit(f"Ошибка в left_click_mode: {str(e)}")
        finally:
            self.signals.update_indicator_signal.emit(False)
            self.left_click_running = False
            stop.clear()

    def right_click_mode(self):
        self.signals.log_signal.emit("ПКМ активирован")
        self.signals.update_indicator_signal.emit(True)
        stop = self._right_stop_event
        try:
            while not stop.is_set():
                pyautogui.rightClick()
                self._wait_breakable(self.click_delay, stop)
                pyautogui.press('space')        # ВСЕГДА жмём пробел
                if stop.is_set():
                    break
                self._wait_breakable(self.space_delay, stop)
        except Exception as e:
            self.signals.log_signal.emit(f"Ошибка в right_click_mode: {str(e)}")
        finally:
            self.signals.update_indicator_signal.emit(False)
            self.right_click_running = False
            stop.clear()

    # ---------- toggles (с кулдауном) ----------
    def _toggle_allowed(self) -> bool:
        now = time.monotonic()
        if (now - self._last_toggle_ts) * 1000.0 < self._toggle_gate_ms:
            return False
        self._last_toggle_ts = now
        return True

    def start_left_click(self):
        if not self._toggle_allowed():
            return
        if self.left_click_running:
            self._play_sound("stop")          # звук сразу
            self._left_stop_event.set()
            self.signals.log_signal.emit("ЛКМ выключен")
            return
        if self.right_click_running:
            self._right_stop_event.set()
            self.signals.log_signal.emit("ПКМ выключен")
        self._left_stop_event.clear()
        self.left_click_running = True
        self._play_sound("start")             # звук сразу
        threading.Thread(target=self.left_click_mode, daemon=True).start()

    def start_right_click(self):
        if not self._toggle_allowed():
            return
        if self.right_click_running:
            self._play_sound("stop")
            self._right_stop_event.set()
            self.signals.log_signal.emit("ПКМ выключен")
            return
        if self.left_click_running:
            self._left_stop_event.set()
            self.signals.log_signal.emit("ЛКМ выключен")
        self._right_stop_event.clear()
        self.right_click_running = True
        self._play_sound("start")
        threading.Thread(target=self.right_click_mode, daemon=True).start()

    # ---------- settings ----------
    def show_settings(self):
        self.settings_window_open = True
        self.settings_btn.clearFocus()
        dialog = SettingsDialog(self.config, self)
        if dialog.exec_():
            self.signals.log_signal.emit("Настройки обновлены")
            # перезапускаем слушатель клавиатуры (бинды могли поменяться)
            if self.keyboard_listener:
                self.keyboard_listener.stop()
            self.keyboard_listener = keyboard.Listener(on_press=self.on_key_press)
            self.keyboard_listener.start()
            self._refresh_info_label()
            self.sound_btn.setChecked(self.config.is_sound_enabled())
            self._update_sound_icon()
            # важное: пересобираем аудио после смены путей
            self._init_audio()
        self.settings_window_open = False
        self.setFocus()

    def closeEvent(self, event):
        if self.left_click_running:
            self._left_stop_event.set()
        if self.right_click_running:
            self._right_stop_event.set()
        if self.mouse_listener:
            self.mouse_listener.stop()
        if self.keyboard_listener:
            self.keyboard_listener.stop()
        self._release_audio()
        self.destroyed.emit()
        event.accept()


# --------------------- settings dialog ----------------------
class SettingsDialog(QDialog):
    def __init__(self, config, parent=None):
        super().__init__(parent)
        self.config = config
        self.current_setting = None
        self.key_listener = None
        self.init_ui()
        self.apply_theme()

    def init_ui(self):
        self.setWindowTitle("Настройки кликера")
        self.setFixedSize(560, 520)

        layout = QVBoxLayout(self)

        # --- Горячие клавиши ---
        box = QGroupBox("Горячие клавиши")
        form = QFormLayout(box)

        self.edits = {}
        self.assign_btns = {}

        def row(key, title):
            h = QHBoxLayout()
            edit = QLineEdit(self.config.get_binding(key) or "")
            edit.setReadOnly(True)
            edit.setPlaceholderText("Не назначено")
            edit.setMinimumWidth(260)
            btn = QPushButton("Назначить")
            btn.clicked.connect(lambda _=False, k=key: self.start_listening(k))
            h.addWidget(edit, 1)
            h.addWidget(btn)
            self.edits[key] = edit
            self.assign_btns[key] = btn
            form.addRow(title, h)

        row("toggle_left",  "Запуск/стоп ЛКМ")
        row("toggle_right", "Запуск/стоп ПКМ")
        row("faster_click", "Быстрее click_delay (→)")
        row("slower_click", "Медленнее click_delay (←)")
        row("faster_space", "Быстрее space_delay (↓)")
        row("slower_space", "Медленнее space_delay (↑)")

        box.setLayout(form)
        layout.addWidget(box)

        # --- Шаг ---
        step_box = QGroupBox("Шаг изменения")
        step_form = QFormLayout(step_box)
        self.step_spin = QDoubleSpinBox()
        self.step_spin.setDecimals(3)
        self.step_spin.setMinimum(0.01)
        self.step_spin.setMaximum(5.0)
        self.step_spin.setSingleStep(0.01)
        self.step_spin.setSuffix(" сек")
        self.step_spin.setValue(self.config.get_step())
        self.step_spin.setFixedWidth(160)
        step_form.addRow("step", self.step_spin)
        layout.addWidget(step_box)

        # --- Звуки ---
        sounds_box = QGroupBox("Звуки (WAV)")
        sounds_form = QFormLayout(sounds_box)

        self.start_wav_edit = QLineEdit(self.config.get_wav_path("start"))
        self.stop_wav_edit  = QLineEdit(self.config.get_wav_path("stop"))
        for e in (self.start_wav_edit, self.stop_wav_edit):
            e.setPlaceholderText("путь к .wav (не обязательно)")
            e.setMinimumWidth(360)

        btn_start = QPushButton("Выбрать…")
        btn_stop  = QPushButton("Выбрать…")
        btn_start.clicked.connect(lambda: self._browse_wav(self.start_wav_edit))
        btn_stop.clicked.connect(lambda: self._browse_wav(self.stop_wav_edit))

        h1 = QHBoxLayout(); h1.addWidget(self.start_wav_edit, 1); h1.addWidget(btn_start)
        h2 = QHBoxLayout(); h2.addWidget(self.stop_wav_edit, 1);  h2.addWidget(btn_stop)

        sounds_form.addRow("Старт:", h1)
        sounds_form.addRow("Стоп:",  h2)
        layout.addWidget(sounds_box)

        # OK/Cancel
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.save_and_close)
        bb.rejected.connect(self.reject)
        layout.addWidget(bb)

    def _browse_wav(self, edit: QLineEdit):
        path, _ = QFileDialog.getOpenFileName(
            self, "Выберите WAV файл", "", "WAV файлы (*.wav)"
        )
        if path:
            edit.setText(path)

    def apply_theme(self):
        self.setStyleSheet("""
            QDialog { background-color: #1E1E1E; color: #DDDDDD; }
            QLabel { color: #DDDDDD; }
            QGroupBox { border:1px solid #444; border-radius:8px; margin-top:10px; padding:10px; }
            QPushButton { background-color: #6A5AF9; color: white; border: none; padding: 6px 10px;
                          border-radius: 4px; font-size: 12px; }
            QPushButton:hover { background-color: #5B4AE9; }
            QLineEdit {
                background:#2A2A2A; color:#EEEEEE; border:1px solid #555;
                border-radius:6px; padding:4px 8px; font-size:14px; min-height:28px;
            }
            QDoubleSpinBox {
                background:#2A2A2A; color:#EEEEEE; border:1px solid #555;
                border-radius:6px; padding:4px 8px; font-size:14px; min-height:28px;
            }
        """)

    def start_listening(self, action):
        self.current_setting = action
        btn = self.assign_btns[action]
        btn.setText("Нажмите клавишу...")
        btn.setStyleSheet("background-color: #4A3AD9; color: white;")
        for k, b in self.assign_btns.items():
            if k != action:
                b.setEnabled(False)
        self.key_listener = keyboard.Listener(on_press=self.on_key_event)
        self.key_listener.start()

    def on_key_event(self, key):
        if not self.current_setting:
            return
        try:
            key_name = key.char
        except AttributeError:
            key_name = str(key).split('.')[-1].lower()

        self.config.set_binding(self.current_setting, key_name)
        self.edits[self.current_setting].setText(key_name)

        btn = self.assign_btns[self.current_setting]
        btn.setText("Назначить")
        btn.setStyleSheet("")

        if self.key_listener:
            self.key_listener.stop()
            self.key_listener = None

        for b in self.assign_btns.values():
            b.setEnabled(True)

        self.current_setting = None

    def save_and_close(self):
        # шаг
        self.config.set_step(self.step_spin.value())
        # звуки
        start_path = self.start_wav_edit.text().strip()
        stop_path  = self.stop_wav_edit.text().strip()
        # позволяем пустые (используются дефолтные из /sounds)
        if start_path and not start_path.lower().endswith(".wav"):
            start_path = ""
        if stop_path and not stop_path.lower().endswith(".wav"):
            stop_path = ""

        self.config.set_wav_path("start", start_path)
        self.config.set_wav_path("stop",  stop_path)
        self.accept()
