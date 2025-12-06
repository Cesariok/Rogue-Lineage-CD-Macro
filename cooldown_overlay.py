import time
import queue
import threading
import tkinter as tk
from tkinter import messagebox
import os
import sys

def resource_path(relative_path: str) -> str:
    """
    Корректно находит путь к файлу и в обычном запуске, и внутри .exe (PyInstaller).
    """
    if hasattr(sys, "_MEIPASS"):
        base_path = sys._MEIPASS
    else:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)



from pynput import keyboard, mouse
from pynput.keyboard import Controller as KBController
from pynput.mouse import Controller as MouseController, Button as MouseButton

CONFIG_FILE = "skills.cfg"

# ---------- чтение конфига ----------

def load_config(path=CONFIG_FILE):
    """
    Формат строки в конфиге:
    кнопка  название(можно с пробелами)  cd  delay_before  delay_after  simulate1  autocast

    Пример:
    1 Basic Feint 4 0.00 0.10 true false
    2 Lethality 40 0.05 0.20 true true
    3 Bane 8 0.00 0.00 false false
    """
    skills = {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                parts = line.split()
                if len(parts) < 7:
                    continue

                key = parts[0]

                autocast_str = parts[-1].lower()
                simulate_str = parts[-2].lower()
                delay_after_str = parts[-3]
                delay_before_str = parts[-4]
                cd_str = parts[-5]

                try:
                    cd = float(cd_str)
                    delay_before = float(delay_before_str)
                    delay_after = float(delay_after_str)
                except ValueError:
                    continue

                simulate_flag = simulate_str == "true"
                autocast_flag = autocast_str == "true"

                name = " ".join(parts[1:-5]) or key

                skills[key] = {
                    "name": name,
                    "cd": cd,
                    "delay_before": delay_before,
                    "delay_after": delay_after,
                    "simulate": simulate_flag,
                    "autocast": autocast_flag,
                }
    except FileNotFoundError:
        print(f"Не найден файл {path}")

    print("Загружены скиллы:")
    for k, v in skills.items():
        print(
            f"  {k}: {v['name']} "
            f"(cd={v['cd']}, before={v['delay_before']}, after={v['delay_after']}, "
            f"simulate1={v['simulate']}, autocast={v['autocast']})"
        )
    return skills


skills = load_config()

last_digit = None
event_queue = queue.Queue()
cooldowns = {}  # key -> {name, end, cd}

kb_controller = KBController()
mouse_controller = MouseController()

# ---------- слушатели клавы и мыши ----------

def on_key_press(key):
    global last_digit, skills
    try:
        ch = key.char
    except AttributeError:
        return

    if ch is not None and ch.isdigit():
        last_digit = ch
        skill = skills.get(ch)
        if not skill:
            return

        # 1) AUTОCAST: цифра -> delay_before -> ЛКМ + старт КД
        if skill.get("autocast"):
            delay_before = skill.get("delay_before", 0.0)

            def auto_cast():
                try:
                    if delay_before > 0:
                        time.sleep(delay_before)
                    # старт КД
                    event_queue.put(("start_cd", ch))
                    # ЛКМ
                    mouse_controller.press(MouseButton.left)
                    mouse_controller.release(MouseButton.left)
                except Exception as e:
                    print("Ошибка автокаста:", e)

            threading.Thread(target=auto_cast, daemon=True).start()

        # 2) НАЖАТИЕ 1: привязано к нажатию цифры
        if skill.get("simulate") and skill["name"].lower() != "bane":
            delay_before = skill.get("delay_before", 0.0)
            delay_after = skill.get("delay_after", 0.0)

            # если автокаст, то 1 жмём после (delay_before + delay_after)
            total_delay = delay_before + delay_after if skill.get("autocast") else delay_after

            def press_one():
                try:
                    if total_delay > 0:
                        time.sleep(total_delay)
                    kb_controller.press('1')
                    kb_controller.release('1')
                except Exception as e:
                    print("Ошибка симуляции клавиши 1:", e)

            threading.Thread(target=press_one, daemon=True).start()


def on_mouse_click(x, y, button, pressed):
    from pynput.mouse import Button
    if button == Button.left and pressed:
        # обычный режим: цифра -> ЛКМ -> старт КД
        if last_digit and last_digit in skills:
            event_queue.put(("start_cd", last_digit))


def start_listeners():
    kb_listener = keyboard.Listener(on_press=on_key_press)
    ms_listener = mouse.Listener(on_click=on_mouse_click)
    kb_listener.start()
    ms_listener.start()


# ---------- GUI-редактор конфига ----------

def create_config_editor(root):
    global skills
    skills = load_config()

    frame = tk.Frame(root)
    frame.pack(padx=10, pady=10)

    headers = ["Key", "Name", "CD", "DelayBefore", "DelayAfter", "Sim1", "Autocast"]
    for col, text in enumerate(headers):
        lbl = tk.Label(frame, text=text, font=("Segoe UI", 10, "bold"))
        lbl.grid(row=0, column=col, padx=3, pady=3)

    rows_vars = []

    for row in range(1, 11):
        key_var = tk.StringVar()
        name_var = tk.StringVar()
        cd_var = tk.StringVar()
        dbefore_var = tk.StringVar()
        dafter_var = tk.StringVar()
        sim_var = tk.BooleanVar()
        auto_var = tk.BooleanVar()

        e_key = tk.Entry(frame, width=4, textvariable=key_var)
        e_name = tk.Entry(frame, width=18, textvariable=name_var)
        e_cd = tk.Entry(frame, width=6, textvariable=cd_var)
        e_dbefore = tk.Entry(frame, width=7, textvariable=dbefore_var)
        e_dafter = tk.Entry(frame, width=7, textvariable=dafter_var)
        c_sim = tk.Checkbutton(frame, variable=sim_var)
        c_auto = tk.Checkbutton(frame, variable=auto_var)

        e_key.grid(row=row, column=0, padx=2, pady=1)
        e_name.grid(row=row, column=1, padx=2, pady=1)
        e_cd.grid(row=row, column=2, padx=2, pady=1)
        e_dbefore.grid(row=row, column=3, padx=2, pady=1)
        e_dafter.grid(row=row, column=4, padx=2, pady=1)
        c_sim.grid(row=row, column=5, padx=2, pady=1)
        c_auto.grid(row=row, column=6, padx=2, pady=1)

        rows_vars.append(
            (key_var, name_var, cd_var, dbefore_var, dafter_var, sim_var, auto_var)
        )

    sorted_items = sorted(skills.items(), key=lambda kv: kv[0])
    for (key, data), row in zip(sorted_items, rows_vars):
        key_var, name_var, cd_var, dbefore_var, dafter_var, sim_var, auto_var = row
        key_var.set(key)
        name_var.set(data["name"])
        cd_var.set(str(data["cd"]))
        dbefore_var.set(str(data.get("delay_before", 0.0)))
        dafter_var.set(str(data.get("delay_after", 0.0)))
        sim_var.set(bool(data.get("simulate", False)))
        auto_var.set(bool(data.get("autocast", False)))

    def apply_config():
        global skills

        lines = []
        for (
            key_var,
            name_var,
            cd_var,
            dbefore_var,
            dafter_var,
            sim_var,
            auto_var,
        ) in rows_vars:
            key = key_var.get().strip()
            name = name_var.get().strip()
            cd_str = cd_var.get().strip()
            dbefore_str = dbefore_var.get().strip()
            dafter_str = dafter_var.get().strip()

            if not key or not name or not cd_str:
                continue

            try:
                cd = float(cd_str)
            except ValueError:
                print(f"Неверный CD в строке с ключом {key}: {cd_str}")
                continue

            try:
                delay_before = float(dbefore_str) if dbefore_str else 0.0
            except ValueError:
                print(f"Неверный delay_before в строке с ключом {key}: {dbefore_str}")
                delay_before = 0.0

            try:
                delay_after = float(dafter_str) if dafter_str else 0.0
            except ValueError:
                print(f"Неверный delay_after в строке с ключом {key}: {dafter_str}")
                delay_after = 0.0

            sim = sim_var.get()
            auto = auto_var.get()

            sim_str = "true" if sim else "false"
            auto_str = "true" if auto else "false"

            line = f"{key} {name} {cd} {delay_before} {delay_after} {sim_str} {auto_str}"
            lines.append(line)

        try:
            with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                for line in lines:
                    f.write(line + "\n")

            skills = load_config()
            messagebox.showinfo("Конфиг", "Изменения применены и записаны в skills.cfg.")
        except Exception as e:
            messagebox.showerror("Ошибка", f"Не удалось записать конфиг:\n{e}")

    btn_apply = tk.Button(root, text="Применить", command=apply_config)
    btn_apply.pack(pady=(0, 10))


# ---------- GUI-оверлей ----------

def run_gui():
    root = tk.Tk()
    root.title("Skill Config + Cooldown Overlay")
    root.iconbitmap(resource_path("icon.ico"))   # ← добавили

    create_config_editor(root)

    overlay = tk.Toplevel(root)
    overlay.title("Cooldown overlay")
    overlay.overrideredirect(True)
    overlay.attributes("-topmost", True)
    overlay.iconbitmap(resource_path("icon.ico"))  # ← и сюда тоже

    overlay.configure(bg="black")
    try:
        overlay.attributes("-transparentcolor", "black")
    except tk.TclError:
        pass

    # Canvas вместо Label, будем рисовать бары
    canvas = tk.Canvas(
        overlay,
        bg="black",
        highlightthickness=0,
    )
    canvas.pack(fill="both", expand=True)

    # фиксированная ширина, левый нижний угол
    overlay.update_idletasks()
    width = 350
    height = 200
    screen_w = overlay.winfo_screenwidth()
    screen_h = overlay.winfo_screenheight()
    overlay.geometry(f"{width}x{height}+20+{screen_h - height - 0}")

    # параметры баров
    bar_height = 22
    bar_gap = 4
    margin_x = 50
    margin_bottom = 10

    def process_events():
        global skills
        now = time.time()

        # события
        while True:
            try:
                ev, key = event_queue.get_nowait()
            except queue.Empty:
                break

            if ev == "start_cd":
                skill = skills.get(key)
                if not skill:
                    continue

                existing = cooldowns.get(key)
                if existing and existing["end"] > now:
                    continue  # КД уже идёт

                cooldowns[key] = {
                    "name": skill["name"],
                    "end": now + skill["cd"],
                    "cd": skill["cd"],
                }

        # убираем закончившиеся
        remove_keys = [k for k, info in cooldowns.items() if info["end"] <= now]
        for k in remove_keys:
            del cooldowns[k]

        # перерисовка canvas
        canvas.delete("all")

        if cooldowns:
            # порядок: старые снизу, новые сверху
            items = list(cooldowns.items())   # [(key, info), ...] в порядке добавления
            num = len(items)

            for idx, (key, info) in enumerate(items):
                remaining = max(0.0, info["end"] - now)
                cd_total = info.get("cd", 1.0) or 1.0
                percent = max(0.0, min(1.0, remaining / cd_total))

                # позиция бара: снизу вверх
                y_bottom = height - margin_bottom - idx * (bar_height + bar_gap)
                y_top = y_bottom - bar_height

                x_left = margin_x
                x_right = width - margin_x

                # "серый фон" бара (как полупрозрачный трек)
                canvas.create_rectangle(
                    x_left,
                    y_top,
                    x_right,
                    y_bottom,
                    fill="#202020",
                    outline="",
                )

                # прогресс (чуть светлее)
                prog_right = x_left + (x_right - x_left) * percent
                canvas.create_rectangle(
                    x_left,
                    y_top,
                    prog_right,
                    y_bottom,
                    fill="#606060",
                    outline="",
                )

                # текст поверх
                text = f"{info['name']}  {remaining:4.1f}"
                canvas.create_text(
                    x_left + 6,
                    (y_top + y_bottom) / 2,
                    text=text,
                    fill="white",
                    font=("Consolas", 11, "bold"),
                    anchor="w",
                )

        overlay.deiconify()
        root.after(100, process_events)

    process_events()
    root.mainloop()


if __name__ == "__main__":
    start_listeners()
    run_gui()
