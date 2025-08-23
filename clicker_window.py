import pyautogui
import time
import threading
import random
import os
import json
from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel,
                             QPushButton, QTextEdit, QDialog,
                             QDialogButtonBox, QFrame)
from PyQt5.QtCore import Qt, QTimer, pyqtSignal, QObject, QSize
from PyQt5.QtGui import QFont, QIcon, QPixmap, QColor
from pynput import mouse, keyboard


class ClickerSignals(QObject):
    log_signal = pyqtSignal(str)
    update_speed_signal = pyqtSignal(str)
    update_indicator_signal = pyqtSignal(bool)


class Config:
    def __init__(self):
        self.config_file = "clicker_config.json"
        self.default_bindings = {
            "left_click": "",
            "right_click": "",
            "speed_slow": "",
            "speed_medium": "",
            "speed_fast": ""
        }
        self.load()

    def load(self):
        if os.path.exists(self.config_file):
            try:
                with open(self.config_file, 'r') as f:
                    self.bindings = json.load(f)
            except:
                self.bindings = self.default_bindings.copy()
        else:
            self.bindings = self.default_bindings.copy()

    def save(self):
        with open(self.config_file, 'w') as f:
            json.dump(self.bindings, f, indent=4)

    def get_binding(self, key):
        return self.bindings.get(key, "")

    def set_binding(self, key, value):
        self.bindings[key] = value
        self.save()


class ClickerWindow(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.signals = ClickerSignals()
        self.signals.log_signal.connect(self.add_log)
        self.signals.update_speed_signal.connect(self.update_speed_display)
        self.signals.update_indicator_signal.connect(self.update_indicator_status)

        self.config = Config()
        self.left_click_running = False
        self.right_click_running = False
        self.min_delay = 0.2
        self.max_delay = 0.4
        self.current_speed = "CRAZY"
        self.mouse_listener = None
        self.keyboard_listener = None
        self.settings_window_open = False  # Флаг для отслеживания открытого окна настроек

        self.init_ui()
        self.apply_theme()
        self.setup_listeners()

    def init_ui(self):
        self.setWindowTitle("Crazy Shah Clicker")
        self.setMinimumSize(600, 400)

        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        layout.setContentsMargins(15, 15, 15, 15)

        # Заголовок с кнопкой настроек
        header_layout = QHBoxLayout()

        title = QLabel("Crazy Shah Clicker")
        title.setFont(QFont("Arial", 16, QFont.Bold))
        title.setStyleSheet("color: #6A5AF9;")
        header_layout.addWidget(title)

        header_layout.addStretch()

        # Кнопка настроек
        self.settings_btn = QPushButton()
        self.settings_btn.setFixedSize(32, 32)
        self.settings_btn.setToolTip("Настройки клавиш")
        if os.path.exists("icons/icon_settings.png"):
            self.settings_btn.setIcon(QIcon("icons/icon_settings.png"))
            self.settings_btn.setIconSize(QSize(24, 24))
        else:
            self.settings_btn.setText("⚙")
        self.settings_btn.setStyleSheet("""
            QPushButton {
                background-color: #444444;
                border: none;
                border-radius: 16px;
                padding: 5px;
            }
            QPushButton:hover {
                background-color: #555555;
            }
        """)
        self.settings_btn.clicked.connect(self.show_settings)
        self.settings_btn.setFocusPolicy(Qt.NoFocus)
        header_layout.addWidget(self.settings_btn)

        layout.addLayout(header_layout)

        # Индикатор скорости
        self.speed_label = QLabel(f"Скорость: {self.current_speed}")
        self.speed_label.setFont(QFont("Arial", 14, QFont.Bold))
        self.update_speed_color()
        layout.addWidget(self.speed_label)

        # Индикатор статуса
        self.status_indicator = QFrame()
        self.status_indicator.setFixedHeight(20)
        self.status_indicator.setStyleSheet("background-color: red; border-radius: 10px;")
        layout.addWidget(self.status_indicator)

        # Консоль вывода
        self.console = QTextEdit()
        self.console.setReadOnly(True)
        self.console.setFont(QFont("Consolas", 12))
        layout.addWidget(self.console)

        # Логи
        self.add_log(f"Текущая скорость: {self.current_speed}")
        self.add_log("Ожидание команд...")
        self.add_log("Настройте клавиши в настройках (иконка шестеренки)")

    def apply_theme(self):
        self.setStyleSheet("""
            QWidget {
                background-color: #1E1E1E;
                color: #DDDDDD;
            }
            QTextEdit {
                background-color: #3A3A3A;
                color: #DDDDDD;
                border: 1px solid #555555;
                border-radius: 4px;
                font-family: Consolas;
                font-size: 12px;
            }
            QLabel {
                color: #DDDDDD;
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
        """)

    def add_log(self, message):
        self.console.append(message)
        # Прокручиваем вниз
        self.console.verticalScrollBar().setValue(
            self.console.verticalScrollBar().maximum()
        )

    def update_indicator_status(self, is_active):
        if is_active:
            self.status_indicator.setStyleSheet("background-color: green; border-radius: 10px;")
        else:
            self.status_indicator.setStyleSheet("background-color: red; border-radius: 10px;")

    def update_speed_display(self, speed_name):
        self.current_speed = speed_name
        self.speed_label.setText(f"Скорость: {self.current_speed}")
        self.update_speed_color()

    def update_speed_color(self):
        colors = {
            "SLOW": "green",
            "MID": "yellow",
            "CRAZY": "red"
        }
        color = colors.get(self.current_speed, "white")
        self.speed_label.setStyleSheet(f"color: {color}; font-weight: bold; font-size: 14px;")

    def setup_listeners(self):
        # Создаем слушатель для боковых кнопок мыши
        self.mouse_listener = mouse.Listener(on_click=self.on_mouse_click)
        self.mouse_listener.start()

        # Создаем слушатель для клавиатуры
        self.keyboard_listener = keyboard.Listener(on_press=self.on_key_press)
        self.keyboard_listener.start()

        self.add_log("Слушатели активированы")

    def on_key_press(self, key):
        # Не обрабатываем клавиши, если открыто окно настроек
        if self.settings_window_open:
            return

        try:
            key_char = key.char
        except AttributeError:
            # Для специальных клавиш
            key_char = str(key).split('.')[-1].lower()

        # Игнорируем пробел (space) чтобы он не открывал настройки
        if key_char == 'space':
            return

        # Проверяем нажатые клавиши
        left_bind = self.config.get_binding("left_click")
        right_bind = self.config.get_binding("right_click")
        slow_bind = self.config.get_binding("speed_slow")
        medium_bind = self.config.get_binding("speed_medium")
        fast_bind = self.config.get_binding("speed_fast")

        if left_bind and key_char == left_bind:
            self.start_left_click()
        elif right_bind and key_char == right_bind:
            self.start_right_click()
        elif slow_bind and key_char == slow_bind:
            self.update_speed("SLOW", 0.8, 1.2)
        elif medium_bind and key_char == medium_bind:
            self.update_speed("MID", 0.4, 0.8)
        elif fast_bind and key_char == fast_bind:
            self.update_speed("CRAZY", 0.2, 0.4)

    def on_mouse_click(self, x, y, button, pressed):
        # Не обрабатываем клики мыши, если открыто окно настроек
        if self.settings_window_open:
            return

        if pressed:
            left_bind = self.config.get_binding("left_click")
            right_bind = self.config.get_binding("right_click")

            if left_bind == "mouse4" and button == mouse.Button.x1:
                self.signals.log_signal.emit("Нажата боковая кнопка 4 мыши (ЛКМ)")
                self.start_left_click()
            elif left_bind == "mouse5" and button == mouse.Button.x2:
                self.signals.log_signal.emit("Нажата боковая кнопка 5 мыши (ЛКМ)")
                self.start_left_click()
            elif right_bind == "mouse4" and button == mouse.Button.x1:
                self.signals.log_signal.emit("Нажата боковая кнопка 4 мыши (ПКМ)")
                self.start_right_click()
            elif right_bind == "mouse5" and button == mouse.Button.x2:
                self.signals.log_signal.emit("Нажата боковая кнопка 5 мыши (ПКМ)")
                self.start_right_click()
            elif button == mouse.Button.x1 and not left_bind and not right_bind:
                self.signals.log_signal.emit("Нажата боковая кнопка 4 мыши (не настроена)")
            elif button == mouse.Button.x2 and not left_bind and not right_bind:
                self.signals.log_signal.emit("Нажата боковая кнопка 5 мыши (не настроена)")

    def update_speed(self, speed_name, new_min, new_max):
        self.min_delay = new_min
        self.max_delay = new_max
        self.signals.log_signal.emit(f"Скорость изменена на: {speed_name}")
        self.signals.update_speed_signal.emit(speed_name)

    def left_click_mode(self):
        self.signals.log_signal.emit("ЛКМ активирован")
        self.signals.update_indicator_signal.emit(True)

        try:
            while self.left_click_running:
                click_delay = random.uniform(self.min_delay, self.max_delay)
                space_delay = random.uniform(self.min_delay, self.max_delay)

                pyautogui.click()

                # Разбиваем задержку на мелкие части для быстрого реагирования
                start_time = time.time()
                while time.time() - start_time < click_delay and self.left_click_running:
                    time.sleep(0.01)  # Проверяем каждые 10мс

                if not self.left_click_running:
                    # Если выключили до нажатия пробела, нажимаем его перед выходом
                    pyautogui.press('space')
                    break

                pyautogui.press('space')

                start_time = time.time()
                while time.time() - start_time < space_delay and self.left_click_running:
                    time.sleep(0.01)  # Проверяем каждые 10мс

        except Exception as e:
            self.signals.log_signal.emit(f"Ошибка в left_click_mode: {str(e)}")
        finally:
            self.signals.update_indicator_signal.emit(False)

    def right_click_mode(self):
        self.signals.log_signal.emit("ПКМ активирован")
        self.signals.update_indicator_signal.emit(True)

        try:
            while self.right_click_running:
                click_delay = random.uniform(self.min_delay, self.max_delay)
                space_delay = random.uniform(self.min_delay, self.max_delay)

                pyautogui.rightClick()

                # Разбиваем задержку на мелкие части для быстрого реагирования
                start_time = time.time()
                while time.time() - start_time < click_delay and self.right_click_running:
                    time.sleep(0.01)  # Проверяем каждые 10мс

                if not self.right_click_running:
                    # Если выключили до нажатия пробела, нажимаем его перед выходом
                    pyautogui.press('space')
                    break

                pyautogui.press('space')

                start_time = time.time()
                while time.time() - start_time < space_delay and self.right_click_running:
                    time.sleep(0.01)  # Проверяем каждые 10мс

        except Exception as e:
            self.signals.log_signal.emit(f"Ошибка в right_click_mode: {str(e)}")
        finally:
            self.signals.update_indicator_signal.emit(False)

    def start_left_click(self):
        if self.left_click_running:
            self.left_click_running = False
            self.signals.log_signal.emit("ЛКМ выключен")
            return

        if self.right_click_running:
            self.right_click_running = False
            self.signals.log_signal.emit("ПКМ выключен")

        self.left_click_running = True
        threading.Thread(target=self.left_click_mode, daemon=True).start()

    def start_right_click(self):
        if self.right_click_running:
            self.right_click_running = False
            self.signals.log_signal.emit("ПКМ выключен")
            return

        if self.left_click_running:
            self.left_click_running = False
            self.signals.log_signal.emit("ЛКМ выключен")

        self.right_click_running = True
        threading.Thread(target=self.right_click_mode, daemon=True).start()

    def show_settings(self):
        self.settings_window_open = True  # Устанавливаем флаг, что окно настроек открыто
        # Убираем фокус с кнопки настроек, чтобы пробел не активировал её после закрытия диалога
        self.settings_btn.clearFocus()
        dialog = SettingsDialog(self.config, self)
        if dialog.exec_():
            self.signals.log_signal.emit("Настройки клавиш обновлены")
            # Перезапускаем слушатели для применения новых настроек
            if self.keyboard_listener:
                self.keyboard_listener.stop()
            self.keyboard_listener = keyboard.Listener(on_press=self.on_key_press)
            self.keyboard_listener.start()
        self.settings_window_open = False  # Сбрасываем флаг после закрытия окна
        # После закрытия диалога возвращаем фокус на основное окно
        self.setFocus()

    def closeEvent(self, event):
        # Останавливаем все процессы при закрытии окна
        self.left_click_running = False
        self.right_click_running = False

        # Останавливаем слушатели
        if self.mouse_listener:
            self.mouse_listener.stop()

        if self.keyboard_listener:
            self.keyboard_listener.stop()

        # Испускаем сигнал destroyed для уведомления основного окна
        self.destroyed.emit()

        event.accept()


class SettingsDialog(QDialog):
    def __init__(self, config, parent=None):
        super().__init__(parent)
        self.config = config
        self.current_setting = None
        self.key_listener = None
        self.mouse_listener = None
        self.init_ui()
        self.apply_theme()

    def init_ui(self):
        self.setWindowTitle("Настройки клавиш")
        self.setFixedSize(500, 350)

        layout = QVBoxLayout(self)

        # Описание
        label = QLabel("Выберите действие и нажмите любую клавишу или кнопку мыши для привязки:")
        label.setWordWrap(True)
        layout.addWidget(label)

        # Кнопки для настройки
        self.buttons = {
            "left_click": QPushButton(f"ЛКМ + ПРОБЕЛ: {self.config.get_binding('left_click') or 'Не назначено'}"),
            "right_click": QPushButton(f"ПКМ + ПРОБЕЛ: {self.config.get_binding('right_click') or 'Не назначено'}"),
            "speed_slow": QPushButton(f"Медленная скорость: {self.config.get_binding('speed_slow') or 'Не назначено'}"),
            "speed_medium": QPushButton(
                f"Средняя скорость: {self.config.get_binding('speed_medium') or 'Не назначено'}"),
            "speed_fast": QPushButton(f"Быстрая скорость: {self.config.get_binding('speed_fast') or 'Не назначено'}")
        }

        for key, button in self.buttons.items():
            button.clicked.connect(lambda checked, k=key: self.start_listening(k))
            layout.addWidget(button)

        # Кнопки диалога
        button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)

    def closeEvent(self, event):
        # При закрытии окна сбрасываем фокус
        if self.parent():
            self.parent().setFocus()
        event.accept()

    def apply_theme(self):
        self.setStyleSheet("""
            QDialog {
                background-color: #1E1E1E;
                color: #DDDDDD;
            }
            QLabel {
                color: #DDDDDD;
            }
            QPushButton {
                background-color: #6A5AF9;
                color: white;
                border: none;
                padding: 8px 16px;
                border-radius: 4px;
                font-size: 12px;
                margin: 5px;
            }
            QPushButton:hover {
                background-color: #5B4AE9;
            }
            QPushButton:pressed {
                background-color: #4A3AD9;
            }
        """)

    def start_listening(self, action):
        self.current_setting = action
        self.buttons[action].setText("Нажмите клавишу или кнопку мыши...")
        self.buttons[action].setStyleSheet("background-color: #4A3AD9; color: white;")

        # Временно отключаем другие кнопки
        for key, button in self.buttons.items():
            if key != action:
                button.setEnabled(False)

        # Начинаем прослушивание клавиатуры и мыши
        self.key_listener = keyboard.Listener(on_press=self.on_key_event)
        self.key_listener.start()

        self.mouse_listener = mouse.Listener(on_click=self.on_mouse_event)
        self.mouse_listener.start()

    def on_key_event(self, key):
        if self.current_setting:
            try:
                key_char = key.char
            except AttributeError:
                # Для специальных клавиш
                key_char = str(key).split('.')[-1].lower()

            # Сохраняем новую клавишу
            self.config.set_binding(self.current_setting, key_char)
            self.buttons[self.current_setting].setText(f"{self.get_action_name(self.current_setting)}: {key_char}")

            # Отключаем прослушивание
            self.stop_listeners()

            self.current_setting = None

    def on_mouse_event(self, x, y, button, pressed):
        if pressed and self.current_setting:
            if button == mouse.Button.x1:
                # Боковая кнопка 4 мыши
                self.config.set_binding(self.current_setting, "mouse4")
                self.buttons[self.current_setting].setText(f"{self.get_action_name(self.current_setting)}: mouse4")
            elif button == mouse.Button.x2:
                # Боковая кнопка 5 мыши
                self.config.set_binding(self.current_setting, "mouse5")
                self.buttons[self.current_setting].setText(f"{self.get_action_name(self.current_setting)}: mouse5")
            else:
                # Игнорируем обычные кнопки мыши
                return

            # Отключаем прослушивание
            self.stop_listeners()

            self.current_setting = None

    def stop_listeners(self):
        if self.key_listener:
            self.key_listener.stop()
        if self.mouse_listener:
            self.mouse_listener.stop()

        # Восстанавливаем кнопки
        for btn in self.buttons.values():
            btn.setEnabled(True)
            btn.setStyleSheet("")

    def get_action_name(self, action):
        names = {
            "left_click": "ЛКМ + ПРОБЕЛ",
            "right_click": "ПКМ + ПРОБЕЛ",
            "speed_slow": "Медленная скорость",
            "speed_medium": "Средняя скорость",
            "speed_fast": "Быстрая скорость"
        }
        return names.get(action, action)