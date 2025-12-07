import time
import queue
import threading
import tkinter as tk
from tkinter import messagebox
import os
import sys

from pynput import keyboard, mouse
from pynput.keyboard import Controller as KBController
from pynput.mouse import Controller as MouseController, Button as MouseButton

CONFIG_FILE = "skills.cfg"

# глобальные настройки, переопределяются из конфига
MANA_BLOCK_DIGIT = "9"
BANE_DIGIT = ""
AUTO_BANE = False
AGILITY_DIGIT = ""
AUTO_AGILITY = False

# служебные флаги
synthetic_depth = 0
mana_block_active = False

def resource_path(relative_path: str) -> str:
    if hasattr(sys, "_MEIPASS"):
        base_path = sys._MEIPASS
    else:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)


# ---------- чтение конфига ----------

def load_config(path=CONFIG_FILE):
    """
    Вверху skills.cfg можно написать, например:

        mana_block_digit=9
        bane_digit=3
        auto_bane=true
        agility_digit=4
        auto_agility=false

    Далее идут строки скиллов в формате:
        key  name...  cd  delay_before  delay_after  simulate1  autocast  weapon_cancel
    """
    global MANA_BLOCK_DIGIT, BANE_DIGIT, AUTO_BANE, AGILITY_DIGIT, AUTO_AGILITY
    skills = {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            lines = f.readlines()

        # ----- читаем заголовок -----
        for raw in lines:
            line = raw.strip()
            if not line:
                continue
            lower = line.lower()
            if lower.startswith("mana_block_digit="):
                val = line.split("=", 1)[1].strip()
                if val:
                    MANA_BLOCK_DIGIT = val
            elif lower.startswith("bane_digit="):
                val = line.split("=", 1)[1].strip()
                BANE_DIGIT = val
            elif lower.startswith("auto_bane="):
                val = line.split("=", 1)[1].strip().lower()
                AUTO_BANE = (val == "true")
            elif lower.startswith("agility_digit="):
                val = line.split("=", 1)[1].strip()
                AGILITY_DIGIT = val
            elif lower.startswith("auto_agility="):
                val = line.split("=", 1)[1].strip().lower()
                AUTO_AGILITY = (val == "true")

        # ----- читаем сами скиллы -----
        for raw in lines:
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            lower = line.lower()
            if (lower.startswith("mana_block_digit=") or
                lower.startswith("bane_digit=") or
                lower.startswith("auto_bane=") or
                lower.startswith("agility_digit=") or
                lower.startswith("auto_agility=")):
                continue

            parts = line.split()
            if len(parts) < 7:
                continue

            key = parts[0]

            if len(parts) >= 8:
                weapon_cancel_str = parts[-1].lower()
                autocast_str = parts[-2].lower()
                simulate_str = parts[-3].lower()
                delay_after_str = parts[-4]
                delay_before_str = parts[-5]
                cd_str = parts[-6]
                name_parts = parts[1:-6]
            else:
                weapon_cancel_str = "false"
                autocast_str = parts[-1].lower()
                simulate_str = parts[-2].lower()
                delay_after_str = parts[-3]
                delay_before_str = parts[-4]
                cd_str = parts[-5]
                name_parts = parts[1:-5]

            try:
                cd = float(cd_str)
                delay_before = float(delay_before_str)
                delay_after = float(delay_after_str)
            except ValueError:
                continue

            simulate_flag = simulate_str == "true"
            autocast_flag = autocast_str == "true"
            weapon_cancel_flag = weapon_cancel_str == "true"

            name = " ".join(name_parts) or key
            skills[key] = {
                "name": name,
                "cd": cd,
                "delay_before": delay_before,
                "delay_after": delay_after,
                "simulate": simulate_flag,
                "autocast": autocast_flag,
                "weapon_cancel": weapon_cancel_flag,
            }
    except FileNotFoundError:
        print(f"Не найден файл {path}")

    print(f"mana_block_digit = {MANA_BLOCK_DIGIT}")
    print(f"bane_digit = {BANE_DIGIT}, auto_bane = {AUTO_BANE}")
    print(f"agility_digit = {AGILITY_DIGIT}, auto_agility = {AUTO_AGILITY}")
    print("Загружены скиллы:")
    for k, v in skills.items():
        print(
            f"  {k}: {v['name']} "
            f"(cd={v['cd']}, before={v['delay_before']}, after={v['delay_after']}, "
            f"simulate1={v['simulate']}, autocast={v['autocast']}, "
            f"weapon_cancel={v.get('weapon_cancel', False)})"
        )
    return skills


skills = load_config()

last_digit = None
event_queue = queue.Queue()
cooldowns = {}

kb_controller = KBController()
mouse_controller = MouseController()


# ---------- утилита безопасного нажатия ----------

def press_key_safely(key_str):
    global synthetic_depth
    synthetic_depth += 1
    try:
        kb_controller.press(key_str)
        kb_controller.release(key_str)
    finally:
        synthetic_depth -= 1


# ---------- авто-каст через таймер (bane/agility) ----------

def cast_auto_skill(digit, label):
    """Нажать число, ЛКМ и 1, а также запустить КД в оверлее."""
    if not digit:
        return
    try:
        print(f"[AUTO] cast {label} on key {digit}")
        # число
        press_key_safely(digit)
        time.sleep(0.02)
        # старт КД в оверлее
        event_queue.put(("start_cd", digit))
        # ЛКМ
        mouse_controller.press(MouseButton.left)
        mouse_controller.release(MouseButton.left)
        time.sleep(0.02)
        # 1
        press_key_safely('1')
    except Exception as e:
        print(f"Ошибка auto {label}:", e)


def auto_bane_worker():
    interval = 45.5
    next_time = time.time() + interval
    while True:
        if AUTO_BANE and BANE_DIGIT:
            now = time.time()
            if now >= next_time:
                cast_auto_skill(BANE_DIGIT, "Bane")
                next_time = now + interval
        else:
            next_time = time.time() + interval
        time.sleep(0.05)


def auto_agility_worker():
    interval = 60.5
    next_time = time.time() + interval
    while True:
        if AUTO_AGILITY and AGILITY_DIGIT:
            now = time.time()
            if now >= next_time:
                cast_auto_skill(AGILITY_DIGIT, "Agility")
                next_time = now + interval
        else:
            next_time = time.time() + interval
        time.sleep(0.05)


# ---------- слушатели клавы и мыши ----------

def on_key_press(key):
    global last_digit, skills, synthetic_depth
    if synthetic_depth > 0:
        return
    try:
        ch = key.char
    except AttributeError:
        return

    if ch is not None and ch.isdigit():
        last_digit = ch
        skill = skills.get(ch)
        if not skill:
            return

        # AUTОCAST
        if skill.get("autocast"):
            delay_before = skill.get("delay_before", 0.0)
            weapon_cancel_flag = skill.get("weapon_cancel", False)

            def auto_cast():
                try:
                    if delay_before > 0:
                        time.sleep(delay_before)
                    # weapon cancel: перед ЛКМ быстро жмём ту же кнопку
                    if weapon_cancel_flag:
                        time.sleep(0.01)
                        press_key_safely(ch)
                        time.sleep(0.01)
                        press_key_safely(ch)
                    # старт КД
                    event_queue.put(("start_cd", ch))
                    # ЛКМ
                    mouse_controller.press(MouseButton.left)
                    mouse_controller.release(MouseButton.left)
                except Exception as e:
                    print("Ошибка автокаста:", e)

            threading.Thread(target=auto_cast, daemon=True).start()

        # simulate 1
        if skill.get("simulate") and skill["name"].lower() != "bane":
            delay_before = skill.get("delay_before", 0.0)
            delay_after = skill.get("delay_after", 0.0)
            total_delay = delay_before + delay_after if skill.get("autocast") else delay_after

            def press_one():
                try:
                    if total_delay > 0:
                        time.sleep(total_delay)
                    press_key_safely('1')
                except Exception as e:
                    print("Ошибка симуляции клавиши 1:", e)

            threading.Thread(target=press_one, daemon=True).start()


def on_mouse_click(x, y, button, pressed):
    global last_digit, skills, mana_block_active, synthetic_depth

    # ЛКМ стартует КД
    if button == MouseButton.left and pressed:
        if last_digit and last_digit in skills:
            event_queue.put(("start_cd", last_digit))

    # MANA BLOCK: Mouse4 (x1)
    if button == MouseButton.x1:
        # нажали боковую
        if pressed:
            if not mana_block_active:
                mana_block_active = True

                def mana_block_loop():
                    global mana_block_active, synthetic_depth
                    try:
                        # выбрать слот с магией
                        press_key_safely(MANA_BLOCK_DIGIT)
                        time.sleep(0.02)
                        # зажать F
                        synthetic_depth += 1
                        try:
                            kb_controller.press('f')
                        finally:
                            synthetic_depth -= 1

                        # пока держим кнопку
                        while mana_block_active:
                            time.sleep(0.01)

                    except Exception as e:
                        print("Ошибка mana block:", e)
                    finally:
                        # отпускаем F
                        synthetic_depth += 1
                        try:
                            kb_controller.release('f')
                        finally:
                            synthetic_depth -= 1
                        # и жмём 1 один раз
                        synthetic_depth += 1
                        try:
                            kb_controller.press('1')
                            kb_controller.release('1')
                        finally:
                            synthetic_depth -= 1

                threading.Thread(target=mana_block_loop, daemon=True).start()
        else:
            # отпустили боковую
            mana_block_active = False


def start_listeners():
    kb_listener = keyboard.Listener(on_press=on_key_press)
    ms_listener = mouse.Listener(on_click=on_mouse_click)
    kb_listener.start()
    ms_listener.start()


def start_auto_threads():
    threading.Thread(target=auto_bane_worker, daemon=True).start()
    threading.Thread(target=auto_agility_worker, daemon=True).start()


# ---------- GUI-редактор конфига ----------

def create_config_editor(root):
    global skills, MANA_BLOCK_DIGIT, BANE_DIGIT, AUTO_BANE, AGILITY_DIGIT, AUTO_AGILITY
    skills = load_config()

    # верхняя панель для mana block / auto bane / auto agility
    mb_frame = tk.Frame(root)
    mb_frame.pack(pady=(5, 0))

    tk.Label(mb_frame, text="Mana Block Digit:", font=("Segoe UI", 10, "bold")).grid(row=0, column=0, sticky="w")
    mb_var = tk.StringVar(value=MANA_BLOCK_DIGIT)
    tk.Entry(mb_frame, width=5, textvariable=mb_var).grid(row=0, column=1, padx=5, sticky="w")

    tk.Label(mb_frame, text="Bane key:", font=("Segoe UI", 10, "bold")).grid(row=1, column=0, sticky="w")
    bane_digit_var = tk.StringVar(value=BANE_DIGIT)
    tk.Entry(mb_frame, width=5, textvariable=bane_digit_var).grid(row=1, column=1, padx=5, sticky="w")
    auto_bane_var = tk.BooleanVar(value=AUTO_BANE)
    tk.Checkbutton(mb_frame, text="Auto Bane", variable=auto_bane_var).grid(row=1, column=2, padx=10, sticky="w")

    tk.Label(mb_frame, text="Agility key:", font=("Segoe UI", 10, "bold")).grid(row=2, column=0, sticky="w")
    ag_digit_var = tk.StringVar(value=AGILITY_DIGIT)
    tk.Entry(mb_frame, width=5, textvariable=ag_digit_var).grid(row=2, column=1, padx=5, sticky="w")
    auto_ag_var = tk.BooleanVar(value=AUTO_AGILITY)
    tk.Checkbutton(mb_frame, text="Auto Agility", variable=auto_ag_var).grid(row=2, column=2, padx=10, sticky="w")

    # таблица скиллов
    frame = tk.Frame(root)
    frame.pack(padx=10, pady=10)

    headers = ["Key", "Name", "CD", "DelayBefore", "DelayAfter", "Sim1", "Autocast", "WCancel"]
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
        wcancel_var = tk.BooleanVar()

        e_key = tk.Entry(frame, width=4, textvariable=key_var)
        e_name = tk.Entry(frame, width=18, textvariable=name_var)
        e_cd = tk.Entry(frame, width=6, textvariable=cd_var)
        e_dbefore = tk.Entry(frame, width=7, textvariable=dbefore_var)
        e_dafter = tk.Entry(frame, width=7, textvariable=dafter_var)
        c_sim = tk.Checkbutton(frame, variable=sim_var)
        c_auto = tk.Checkbutton(frame, variable=auto_var)
        c_wcancel = tk.Checkbutton(frame, variable=wcancel_var)

        e_key.grid(row=row, column=0, padx=2, pady=1)
        e_name.grid(row=row, column=1, padx=2, pady=1)
        e_cd.grid(row=row, column=2, padx=2, pady=1)
        e_dbefore.grid(row=row, column=3, padx=2, pady=1)
        e_dafter.grid(row=row, column=4, padx=2, pady=1)
        c_sim.grid(row=row, column=5, padx=2, pady=1)
        c_auto.grid(row=row, column=6, padx=2, pady=1)
        c_wcancel.grid(row=row, column=7, padx=2, pady=1)

        rows_vars.append(
            (key_var, name_var, cd_var, dbefore_var, dafter_var, sim_var, auto_var, wcancel_var)
        )

    # заполнение таблицы из skills
    sorted_items = sorted(skills.items(), key=lambda kv: kv[0])
    for (key, data), row in zip(sorted_items, rows_vars):
        key_var, name_var, cd_var, dbefore_var, dafter_var, sim_var, auto_var, wcancel_var = row
        key_var.set(key)
        name_var.set(data["name"])
        cd_var.set(str(data["cd"]))
        dbefore_var.set(str(data.get("delay_before", 0.0)))
        dafter_var.set(str(data.get("delay_after", 0.0)))
        sim_var.set(bool(data.get("simulate", False)))
        auto_var.set(bool(data.get("autocast", False)))
        wcancel_var.set(bool(data.get("weapon_cancel", False)))

    def apply_config():
        global skills

        lines = []

        mb_digit = mb_var.get().strip()
        if mb_digit and not mb_digit.isdigit():
            messagebox.showerror("Ошибка", "Mana Block Digit должен быть цифрой.")
            return
        if not mb_digit:
            mb_digit = "9"

        bane_digit = bane_digit_var.get().strip()
        ag_digit = ag_digit_var.get().strip()
        auto_bane_flag = auto_bane_var.get()
        auto_ag_flag = auto_ag_var.get()

        if auto_bane_flag and not bane_digit:
            messagebox.showerror("Ошибка", "Укажи цифру для Bane или отключи Auto Bane.")
            return
        if auto_ag_flag and not ag_digit:
            messagebox.showerror("Ошибка", "Укажи цифру для Agility или отключи Auto Agility.")
            return

        # заголовок конфига
        lines.append(f"mana_block_digit={mb_digit}")
        lines.append(f"bane_digit={bane_digit}")
        lines.append(f"auto_bane={'true' if auto_bane_flag else 'false'}")
        lines.append(f"agility_digit={ag_digit}")
        lines.append(f"auto_agility={'true' if auto_ag_flag else 'false'}")
        lines.append("")

        # строки скиллов
        for (
            key_var,
            name_var,
            cd_var,
            dbefore_var,
            dafter_var,
            sim_var,
            auto_var,
            wcancel_var,
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
            wcancel = wcancel_var.get()

            sim_str = "true" if sim else "false"
            auto_str = "true" if auto else "false"
            wcancel_str = "true" if wcancel else "false"

            line = f"{key} {name} {cd} {delay_before} {delay_after} {sim_str} {auto_str} {wcancel_str}"
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
    try:
        root.iconbitmap(resource_path("icon.ico"))
    except Exception:
        pass

    create_config_editor(root)

    overlay = tk.Toplevel(root)
    overlay.title("Cooldown overlay")
    overlay.overrideredirect(True)
    overlay.attributes("-topmost", True)
    try:
        overlay.iconbitmap(resource_path("icon.ico"))
    except Exception:
        pass

    overlay.configure(bg="black")
    try:
        overlay.attributes("-transparentcolor", "black")
    except tk.TclError:
        pass

    canvas = tk.Canvas(
        overlay,
        bg="black",
        highlightthickness=0,
    )
    canvas.pack(fill="both", expand=True)

    overlay.update_idletasks()
    width = 350
    height = 200
    screen_w = overlay.winfo_screenwidth()
    screen_h = overlay.winfo_screenheight()
    overlay.geometry(f"{width}x{height}+20+{screen_h - height - 0}")

    bar_height = 22
    bar_gap = 4
    margin_x = 50
    margin_bottom = 10

    def process_events():
        now = time.time()

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
                    continue

                cooldowns[key] = {
                    "name": skill["name"],
                    "end": now + skill["cd"],
                    "cd": skill["cd"],
                }

        remove_keys = [k for k, info in cooldowns.items() if info["end"] <= now]
        for k in remove_keys:
            del cooldowns[k]

        canvas.delete("all")

        if cooldowns:
            items = list(cooldowns.items())
            for idx, (key, info) in enumerate(items):
                remaining = max(0.0, info["end"] - now)
                cd_total = info.get("cd", 1.0) or 1.0
                percent = max(0.0, min(1.0, remaining / cd_total))

                y_bottom = height - margin_bottom - idx * (bar_height + bar_gap)
                y_top = y_bottom - bar_height

                x_left = margin_x
                x_right = width - margin_x

                canvas.create_rectangle(
                    x_left,
                    y_top,
                    x_right,
                    y_bottom,
                    fill="#202020",
                    outline="",
                )

                prog_right = x_left + (x_right - x_left) * percent
                canvas.create_rectangle(
                    x_left,
                    y_top,
                    prog_right,
                    y_bottom,
                    fill="#606060",
                    outline="",
                )

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
    start_auto_threads()
    run_gui()
