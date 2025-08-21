import pyautogui
import keyboard
import time
import threading
import random
from pynput import mouse

# Флаги для управления работой скрипта
left_click_running = False
right_click_running = False

# Текущие настройки задержек (по умолчанию: 0.1-0.4)
min_delay = 0.1
max_delay = 0.4
current_speed = "Быстрая"

def update_speed(speed_name, new_min, new_max):
    """Обновление настроек скорости"""
    global min_delay, max_delay, current_speed
    min_delay = new_min
    max_delay = new_max
    current_speed = speed_name
    print(f"Скорость: {speed_name}")

def left_click_mode():
    """Режим ЛКМ + пробел со случайными задержками"""
    global left_click_running, min_delay, max_delay
    print("ЛКМ активирован")
    while left_click_running:
        # Рандомные задержки с текущими настройками
        click_delay = random.uniform(min_delay, max_delay)
        space_delay = random.uniform(min_delay, max_delay)

        pyautogui.click()  # ЛКМ в текущей позиции
        time.sleep(click_delay)
        pyautogui.press('space')
        time.sleep(space_delay)

def right_click_mode():
    """Режим ПКМ + пробел со случайными задержками"""
    global right_click_running, min_delay, max_delay
    print("ПКМ активирован")
    while right_click_running:
        # Рандомные задержки с текущими настройками
        click_delay = random.uniform(min_delay, max_delay)
        space_delay = random.uniform(min_delay, max_delay)

        pyautogui.rightClick()  # ПКМ в текущей позиции
        time.sleep(click_delay)
        pyautogui.press('space')
        time.sleep(space_delay)

def start_left_click():
    """Активация ЛКМ режима"""
    global left_click_running, right_click_running

    if left_click_running:
        left_click_running = False
        print("ЛКМ выключен")
        return

    if right_click_running:
        right_click_running = False
        print("ПКМ выключен")

    left_click_running = True
    threading.Thread(target=left_click_mode, daemon=True).start()

def start_right_click():
    """Активация ПКМ режима"""
    global right_click_running, left_click_running

    if right_click_running:
        right_click_running = False
        print("ПКМ выключен")
        return

    if left_click_running:
        left_click_running = False
        print("ЛКМ выключен")

    right_click_running = True
    threading.Thread(target=right_click_mode, daemon=True).start()

def on_mouse_click(x, y, button, pressed):
    """Обработка нажатий кнопок мыши"""
    if pressed:
        if button == mouse.Button.x2:  # Боковая кнопка 4 (обычно задняя)
            print("Нажата боковая кнопка 4 мыши (ЛКМ)")
            start_left_click()
        elif button == mouse.Button.x1:  # Боковая кнопка 5 (обычно передняя)
            print("Нажата боковая кнопка 5 мыши (ПКМ)")
            start_right_click()

# Основной код
print("=" * 50)
print("META SCALP CLICKER ПРО ВЕРСИЯ")
print("=" * 50)
print("УПРАВЛЕНИЕ:")
print("[ : ЛКМ + ПРОБЕЛ")
print("] : ПКМ + ПРОБЕЛ")
print("Боковая кнопка 4 мыши : ЛКМ + ПРОБЕЛ")
print("Боковая кнопка 5 мыши : ПКМ + ПРОБЕЛ")
print("← : Средняя скорость")
print("↓ : Быстрая скорость")
print("→ : Ультра скорость")
print("=" * 50)
print(f"Текущая скорость: {current_speed}")
print("=" * 50)
print("Ожидание команд...")

# Регистрация горячих клавиш
keyboard.add_hotkey('[', start_left_click)
keyboard.add_hotkey(']', start_right_click)
keyboard.add_hotkey('left', lambda: update_speed("SLOW", 0.8, 1.2))
keyboard.add_hotkey('down', lambda: update_speed("MID", 0.4, 0.8))
keyboard.add_hotkey('right', lambda: update_speed("CRAZY", 0.1, 0.4))

# Запуск слушателя мыши в отдельном потоке
mouse_listener = mouse.Listener(on_click=on_mouse_click)
mouse_listener.start()

# Вечное ожидание
keyboard.wait()