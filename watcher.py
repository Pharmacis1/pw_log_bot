import time
import os
import glob
import sys
import logging
import threading
import tkinter as tk
from tkinter import scrolledtext
from tkinter import messagebox, filedialog
from PIL import Image, ImageDraw
import pystray
import requests
from datetime import datetime

# --- CONFIG ---
TARGET_SUFFIX = os.path.join("element", "userdata", "FactionData", "FactionHistoryData")
CONFIG_FILE = "watcher.ini"
SERVER_URL = "https://requiem.share.zrok.io"
CHECK_INTERVAL = 60
APP_NAME = "PWLogWatcher"
LOG_FILE = "watcher.log"

# --- LOGGING ---
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(LOG_FILE, encoding='utf-8'),
        logging.StreamHandler()
    ]
)

# --- UTILS ---
# --- UTILS ---
def find_game_path():
    """Ищет папку с логами игры. Сначала конфиг, потом стандартные пути, потом ручной выбор."""
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
            saved_path = f.read().strip()
            if os.path.exists(saved_path):
                logging.info(f"[PATH] Найден сохраненный путь: {saved_path}")
                return saved_path

    logging.info("[PATH] Проверка стандартных путей...")
    common_paths = [
        r"C:\VK Play\Perfect World", r"D:\VK Play\Perfect World",
        r"C:\Games\Perfect World", r"D:\Games\Perfect World",
        r"C:\Program Files (x86)\Perfect World", os.path.expanduser("~")
    ]
    
    for base in common_paths:
        full = os.path.join(base, TARGET_SUFFIX)
        if os.path.exists(full):
            return save_path(full)

    # Если не нашли - спрашиваем пользователя
    logging.info("[PATH] Автоматический поиск не дал результатов. Запрос папки у пользователя...")
    return ask_user_for_path()

def ask_user_for_path():
    """Показывает диалог выбора папки."""
    root = tk.Tk()
    root.withdraw() # Скрыть основное окно
    
    # Пытаемся объяснить пользователю, что нужно
    tk.messagebox.showinfo(
        "Настройка PW Requiem", 
        "Папка с логами Perfect World не найдена автоматически.\n\n"
        "Пожалуйста, укажите папку игры вручную.\n"
        "Обычно это: .../Perfect World"
    )
    
    selected_dir = tk.filedialog.askdirectory(title="Выберите папку Perfect World")
    root.destroy()
    
    if selected_dir:
        # Проверяем, есть ли там нужная подпапка, или это корень
        # Пытаемся найти TARGET_SUFFIX внутри выбранной
        candidate_full = os.path.join(selected_dir, TARGET_SUFFIX)
        if os.path.exists(candidate_full):
            return save_path(candidate_full)
        
        # Может пользователь выбрал саму папку FactionHistoryData?
        if os.path.basename(selected_dir) == "FactionHistoryData":
            return save_path(selected_dir)
            
        # Если выбрали просто папку игры, но структуры нет
        logging.warning(f"[PATH] В выбранной папке {selected_dir} не найдена структура {TARGET_SUFFIX}")
        tk.messagebox.showwarning("Ошибка", f"В выбранной папке не найдена подпапка {TARGET_SUFFIX}.\nПроверьте, что вы выбрали правильную папку игры.")
        return None
        
    logging.warning("[PATH] Пользователь отменил выбор папки.")
    return None

def save_path(path):
    try:
        with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
            f.write(path)
        logging.info(f"[PATH] Путь сохранен: {path}")
    except Exception as e:
        logging.error(f"[ERR] Не удалось сохранить конфиг: {e}")
    return path

def get_startup_shortcut_path():
    return os.path.join(os.getenv('APPDATA'), r'Microsoft\Windows\Start Menu\Programs\Startup', f'{APP_NAME}.lnk')

def is_in_startup():
    return os.path.exists(get_startup_shortcut_path())

def set_startup(enable=True):
    shortcut_path = get_startup_shortcut_path()
    
    if enable:
        if os.path.exists(shortcut_path): return # Уже есть
        
        exe_path = sys.executable
        script_path = os.path.abspath(__file__)
        working_dir = os.path.dirname(script_path)
        
        # Если запущен как скрипт .py
        if script_path.endswith(".py"):
            target = exe_path
            args = f'"{script_path}"'
        else:
            # Если запущен как .exe
            target = script_path
            args = ""
            
        create_shortcut_vbs(target, shortcut_path, args, working_dir)
        logging.info("[SYS] Ярлык автозагрузки создан")
    else:
        if os.path.exists(shortcut_path):
            try:
                os.remove(shortcut_path)
                logging.info("[SYS] Ярлык автозагрузки удален")
            except Exception as e:
                logging.error(f"[ERR] Ошибка удаления ярлыка: {e}")

def create_shortcut_vbs(target, shortcut_path, arguments, working_dir):
    """Создает ярлык через временный VBS скрипт (чтобы не тянуть pywin32)"""
    vbs_content = f"""
    Set oWS = WScript.CreateObject("WScript.Shell")
    sLinkFile = "{shortcut_path}"
    Set oLink = oWS.CreateShortcut(sLinkFile)
    oLink.TargetPath = "{target}"
    oLink.Arguments = "{arguments}"
    oLink.WorkingDirectory = "{working_dir}"
    oLink.WindowStyle = 7 ' Minimized
    oLink.Save
    """
    
    vbs_path = os.path.join(os.environ['TEMP'], 'create_shortcut.vbs')
    try:
        with open(vbs_path, 'w', encoding='cp1251') as f: # VBS system encoding usually
            f.write(vbs_content)
        
        os.system(f'cscript //nologo "{vbs_path}"')
    except Exception as e:
        logging.error(f"[ERR] Ошибка создания VBS: {e}")
    finally:
        if os.path.exists(vbs_path):
            try: os.remove(vbs_path)
            except: pass

# --- THREADED WATCHER ---
class WatcherThread(threading.Thread):
    def __init__(self):
        super().__init__()
        self.stop_event = threading.Event()
        self.game_log_dir = None

    def run(self):
        logging.info("[THREAD] Запуск потока слежения...")
        self.game_log_dir = find_game_path()
        
        if not self.game_log_dir:
            logging.error("[THREAD] Папка не найдена, слежение отключено.")
            return

        logging.info(f"[THREAD] Слежение за: {self.game_log_dir}")
        set_startup(True) # Default enable on run if successful

        while not self.stop_event.is_set():
            try:
                self.check_files()
            except Exception as e:
                logging.error(f"[THREAD] Ошибка цикла: {e}")
            
            # Wait with check for stop interval
            for _ in range(CHECK_INTERVAL):
                if self.stop_event.is_set(): break
                time.sleep(1)

    def check_files(self):
        pattern = os.path.join(self.game_log_dir, "FactionBoard*")
        files = glob.glob(pattern)
        for filepath in files:
            try:
                mtime = os.path.getmtime(filepath)
                if time.time() - mtime < 300: # 5 min age
                    continue
            except OSError:
                continue

            if self.upload_file(filepath):
                try:
                    os.remove(filepath)
                    logging.info(f"[DEL] Удален: {filepath}")
                except Exception as e:
                    logging.error(f"[ERR] Не удален {filepath}: {e}")

    def upload_file(self, filepath):
        url = f"{SERVER_URL}/api/upload"
        logging.info(f"[UPLOAD] {os.path.basename(filepath)}")
        try:
            with open(filepath, 'rb') as f:
                files = {'file': (os.path.basename(filepath), f)}
                headers = {
                    "ngrok-skip-browser-warning": "true",
                    "skip_zrok_interstitial": "true",
                    "User-Agent": "PwLogWatcher/1.0"
                }
                response = requests.post(url, files=files, headers=headers)
                
            if response.status_code == 200:
                res = response.json()
                if res.get("status") == "ok":
                    logging.info(f"[OK] {res.get('new_events')} новых строк")
                    return True
                else:
                    logging.warn(f"[WARN] Сервер: {res}")
            else:
                logging.error(f"[ERR] HTTP {response.status_code}")
        except Exception as e:
            logging.error(f"[ERR] Соединение: {e}")
        return False

    def stop(self):
        self.stop_event.set()

# --- GUI ---
def create_image():
    # Create an icon with a 'W'
    width = 64
    height = 64
    color1 = "black"
    color2 = "white"
    image = Image.new('RGB', (width, height), color1)
    dc = ImageDraw.Draw(image)
    dc.rectangle((width // 2 - 10, 0, width // 2 + 10, height), fill=color2)
    dc.rectangle((0, height // 2 - 10, width, height // 2 + 10), fill=color2)
    return image

def show_logs():
    root = tk.Tk()
    root.title("PW Requiem History - Logs")
    root.geometry("600x400")
    
    text_area = scrolledtext.ScrolledText(root, wrap=tk.WORD, width=40, height=10)
    text_area.pack(expand=True, fill='both')
    
    if os.path.exists(LOG_FILE):
        with open(LOG_FILE, 'r', encoding='utf-8') as f:
            text_area.insert(tk.INSERT, f.read())
    else:
        text_area.insert(tk.INSERT, "Log file not found.")
    
    text_area.configure(state='disabled')
    root.mainloop()

def on_clicked(icon, item):
    if str(item) == "Открыть логи":
        t = threading.Thread(target=show_logs)
        t.daemon = True
        t.start()
    elif str(item) == "Выход":
        icon.stop()

def toggle_startup(icon, item):
    is_on = is_in_startup()
    set_startup(not is_on)

def get_menu_items():
    return (
        pystray.MenuItem("Открыть логи", on_clicked),
        pystray.MenuItem("Автозапуск", toggle_startup, checked=lambda item: is_in_startup()),
        pystray.MenuItem("Выход", on_clicked)
    )

def main():
    # Start Watcher Thread
    watcher = WatcherThread()
    watcher.start()
    
    # Start Tray Icon
    icon = pystray.Icon("PW_Requiem", create_image(), "PW Requiem Watcher", menu=pystray.Menu(get_menu_items))
    
    try:
        icon.run()
    finally:
        watcher.stop()
        watcher.join()

if __name__ == "__main__":
    main()
