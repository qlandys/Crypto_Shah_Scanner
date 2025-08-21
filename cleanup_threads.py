import os
import signal
import threading
import psutil
import time


def kill_child_processes(parent_pid):
    """Рекурсивно завершает все дочерние процессы"""
    try:
        parent = psutil.Process(parent_pid)
        children = parent.children(recursive=True)
        for child in children:
            try:
                child.terminate()
            except psutil.NoSuchProcess:
                pass

        # Ждем завершения процессов
        gone, alive = psutil.wait_procs(children, timeout=3)
        for child in alive:
            try:
                child.kill()
            except:
                pass
    except Exception:
        pass


def cleanup_threads():
    """Принудительно завершает все дочерние потоки и процессы"""
    # Завершаем все активные потоки
    for thread in threading.enumerate():
        if thread is not threading.main_thread():
            try:
                if hasattr(thread, 'terminate'):
                    thread.terminate()
                elif hasattr(thread, '_stop'):
                    thread._stop()
                elif hasattr(thread, 'cancel'):
                    thread.cancel()
            except Exception:
                pass

    # Убиваем все дочерние процессы
    kill_child_processes(os.getpid())

    # Дополнительная очистка для Playwright
    for proc in psutil.process_iter():
        try:
            if "playwright" in proc.name().lower() or "chromium" in proc.name().lower():
                proc.kill()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass


def register_cleanup():
    """Регистрирует обработчики для корректного завершения"""
    import atexit
    atexit.register(cleanup_threads)

    # Обработка сигналов ОС
    signal.signal(signal.SIGTERM, lambda s, f: os._exit(0))
    signal.signal(signal.SIGINT, lambda s, f: os._exit(0))