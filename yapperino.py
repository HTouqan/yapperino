"""
Yapperino — local voice-to-text for Windows.
Trigger your shortcut (single key OR combo, hold OR double-tap), talk, release.
Whisper transcribes and pastes into the focused window.

UI:
  - Tray icon (gray idle, red recording, amber transcribing, dim gray paused)
  - Pill (bottom-center) shows while active
  - Control window: status, Pause, trigger mode, shortcut chooser (combos supported),
    sound on/off, mute-system-audio, "Start with Windows", word counter,
    transcript history (click row to copy; thin separator between rows)

Settings persist to %LOCALAPPDATA%/Yapperino/config.json.
Launch with --background to start hidden (used by Windows startup entry).
"""
import os
import sys
import time
import json
import queue
import atexit
import threading
import winreg

import numpy as np
import sounddevice as sd
import pyperclip
import tkinter as tk
from pynput import keyboard
from pynput.keyboard import Controller, Key, KeyCode
from faster_whisper import WhisperModel
import pystray
from PIL import Image, ImageDraw, ImageTk

# ---------- config ----------
__version__ = "0.3.0"
SAMPLE_RATE = 16000
MIN_AUDIO_SECONDS = 0.3
# Below this peak amplitude the capture is effectively digital silence — the
# mic is muted (hardware tap / OS privacy block) or the wrong device is default.
# Warn instead of running a doomed transcription that returns nothing.
SILENCE_PEAK = 0.004
DOUBLE_TAP_WINDOW = 0.40
HISTORY_CAP = 50
HISTORY_PREVIEW_CHARS = 240   # display cap per row; full text still copied

# Transcription quality tiers. All run locally on CPU (int8); no GPU needed.
# Speed measured on a Ryzen 7 7800X3D as fraction of audio length (lower is
# faster): small ~0.12x, medium ~0.39x, turbo ~0.30x, large-v3 ~0.69x.
# Turbo is large-v3-class yet as quick as medium; large-v3 is the most
# accurate base model but the slowest.
QUALITY_TIERS = [
    ("Fast (small)",         "small.en"),
    ("Balanced (medium)",    "medium.en"),
    ("High (turbo)",         "large-v3-turbo"),
    ("Max (large-v3, slow)", "large-v3"),
]
DEFAULT_MODEL = "medium.en"
_MODEL_BY_QUALITY = {lbl: m for lbl, m in QUALITY_TIERS}
_QUALITY_BY_MODEL = {m: lbl for lbl, m in QUALITY_TIERS}

# Coined service names Whisper can't know on its own. Biases decoding toward
# these spellings instead of the nearest English word ("traffic" for Traefik,
# "image" for immich). Editable in config.json -> "vocabulary".
DEFAULT_VOCAB = ("Traefik, immich, smeepo, gluetun, MikroTik, qBittorrent, "
                 "Sonarr, Radarr, Lidarr, Prowlarr, Bazarr, Proxmox, "
                 "Cloudflare, Proton, Jellyfin, Navidrome")

# Whisper's near-silence hallucinations (YouTube training artifacts). Dropped
# only when one is the ENTIRE transcript, so normal dictation is never touched.
HALLUCINATION_JUNK = {
    "thanks for watching",
    "thank you for watching",
    "please subscribe",
    "like and subscribe",
    "see you in the next video",
    "subtitles by the amara.org community",
}

REG_RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
REG_APP_NAME = "Yapperino"

COL_BG       = "#1a1a1c"
COL_PANEL    = "#26262a"
COL_PANEL_HI = "#33333a"
COL_SEP      = "#52525c"   # thin separator line between history rows
COL_TEXT     = "#f0f0f2"
COL_MUTED    = "#8a8a90"
COL_REC      = "#ff5b5b"
COL_BUSY     = "#ffc857"
COL_IDLE     = "#9aa0a6"
COL_OK       = "#7ed957"
TRANSPARENT  = "#010203"

# Shortcut options. Right-side modifiers are safe alone (rarely misclicked);
# Left modifiers only appear as part of combos.
SHORTCUT_OPTIONS = [
    ("Right Ctrl",          frozenset({Key.ctrl_r})),
    ("Right Alt",           frozenset({Key.alt_r})),
    ("Right Shift",         frozenset({Key.shift_r})),
    ("Right Win",           frozenset({Key.cmd_r})),
    ("Left Ctrl + Win",     frozenset({Key.ctrl_l, Key.cmd})),    # Wispr Flow style
    ("Right Ctrl + Win",    frozenset({Key.ctrl_r, Key.cmd_r})),
    ("Left Alt + Win",      frozenset({Key.alt_l, Key.cmd})),
    ("Right Alt + Win",     frozenset({Key.alt_r, Key.cmd_r})),
    ("Right Ctrl + Shift",  frozenset({Key.ctrl_r, Key.shift_r})),
    ("Right Ctrl + Alt",    frozenset({Key.ctrl_r, Key.alt_r})),
    ("Left Ctrl + Shift",   frozenset({Key.ctrl_l, Key.shift_l})),
    ("Left Ctrl + Alt",     frozenset({Key.ctrl_l, Key.alt_l})),
]
_LABEL_BY_KEY = {keys: lbl for lbl, keys in SHORTCUT_OPTIONS}
_KEY_BY_LABEL = {lbl: keys for lbl, keys in SHORTCUT_OPTIONS}
DEFAULT_HOTKEY = frozenset({Key.ctrl_r})

def _ser_single(k) -> str:
    if hasattr(k, 'name') and k.name:
        return k.name
    if hasattr(k, 'char') and k.char:
        return f"char:{k.char}"
    return "ctrl_r"

def _parse_single(s: str):
    if s.startswith("char:"):
        return KeyCode.from_char(s[5:])
    return getattr(Key, s, Key.ctrl_r)

def serialize_hotkey(k: frozenset) -> str:
    return "+".join(sorted(_ser_single(x) for x in k))

def parse_hotkey(s: str) -> frozenset:
    if not s: return DEFAULT_HOTKEY
    parts = s.split("+")
    return frozenset(_parse_single(p) for p in parts)

def key_display(k: frozenset) -> str:
    return _LABEL_BY_KEY.get(k, serialize_hotkey(k))

# ---------- paths + log ----------
APP_DIR = os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), "Yapperino")
os.makedirs(APP_DIR, exist_ok=True)
LOG_PATH    = os.path.join(APP_DIR, "yapperino.log")
CONFIG_PATH = os.path.join(APP_DIR, "config.json")

# One-time migration from the old "Flow" app dir (pre-rename).
def _migrate_from_flow():
    old_dir = os.path.join(os.environ.get("LOCALAPPDATA", ""), "Flow")
    if not os.path.isdir(old_dir): return
    if os.path.exists(CONFIG_PATH): return
    try:
        import shutil
        for fn in os.listdir(old_dir):
            src = os.path.join(old_dir, fn)
            dst = os.path.join(APP_DIR, fn.replace("flow.log", "yapperino.log"))
            if os.path.isfile(src) and not os.path.exists(dst):
                shutil.copy2(src, dst)
    except Exception:
        pass
_migrate_from_flow()

def log(msg: str) -> None:
    line = f"{time.strftime('%H:%M:%S')} {msg}\n"
    try:
        with open(LOG_PATH, "a", encoding="utf-8") as f: f.write(line)
    except Exception: pass
    try: print(line.rstrip())
    except Exception: pass

# ---------- persistent settings ----------
DEFAULTS = {
    "mode":           "hold",
    "sound_enabled":  True,
    "mute_audio":     False,
    "total_words":    0,
    "total_sessions": 0,
    "hotkey":         "ctrl_r",
    "history":        [],
    "model":          DEFAULT_MODEL,
    "vocabulary":     DEFAULT_VOCAB,
    "beam_size":      5,
}

def load_config() -> dict:
    if not os.path.exists(CONFIG_PATH):
        return dict(DEFAULTS)
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        return {**DEFAULTS, **data}
    except Exception as e:
        log(f"config load failed: {e}")
        return dict(DEFAULTS)

cfg = load_config()
mode             = cfg["mode"]
sound_enabled    = cfg["sound_enabled"]
mute_audio_pref  = cfg["mute_audio"]
total_words      = cfg["total_words"]
total_sessions   = cfg["total_sessions"]
HOTKEY           = parse_hotkey(cfg["hotkey"])
if HOTKEY not in _LABEL_BY_KEY:
    HOTKEY = DEFAULT_HOTKEY
history          = list(cfg["history"])[:HISTORY_CAP]
model_name       = cfg["model"] or DEFAULT_MODEL
vocabulary       = cfg["vocabulary"]
try:
    beam_size    = max(1, int(cfg["beam_size"]))
except (TypeError, ValueError):
    beam_size    = 5
model_loading    = False

def save_config() -> None:
    try:
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump({
                "mode":           mode,
                "sound_enabled":  sound_enabled,
                "mute_audio":     mute_audio_pref,
                "total_words":    total_words,
                "total_sessions": total_sessions,
                "hotkey":         serialize_hotkey(HOTKEY),
                "history":        history[:HISTORY_CAP],
                "model":          model_name,
                "vocabulary":     vocabulary,
                "beam_size":      beam_size,
            }, f, indent=2)
    except Exception as e:
        log(f"config save failed: {e}")

# ---------- model ----------
def _new_model(name: str) -> WhisperModel:
    return WhisperModel(name, device="cpu", compute_type="int8")

log(f"loading model {model_name}")
try:
    model = _new_model(model_name)
except Exception as e:
    log(f"model {model_name} load failed ({e}); falling back to small.en")
    model_name = "small.en"
    model = _new_model(model_name)
log("model ready")

# ---------- runtime state ----------
kb = Controller()
audio_q: "queue.Queue[np.ndarray]" = queue.Queue()
recording = False
paused = False
busy_lock = threading.Lock()
state = "idle"

keys_down: set = set()
combo_satisfied = False
last_tap_time = 0.0
muted_by_us = False

tk_root: tk.Tk | None = None
pill_win = pill_canvas = pill_dot = pill_text = None
ctrl_status_canvas = ctrl_status_dot_id = None
ctrl_status_lbl = ctrl_hint_lbl = ctrl_toggle_btn = None
ctrl_mode_var = ctrl_startup_var = ctrl_sound_var = ctrl_mute_var = None
ctrl_shortcut_var = ctrl_words_lbl = ctrl_copied_lbl = ctrl_quality_var = None
history_inner = history_canvas = None
tray: pystray.Icon | None = None

# ---------- sounds: V6 (D5 ↔ A5), reversed on release ----------
def _pluck(freq: float, duration: float, amp: float, glide_cents: float = -22) -> np.ndarray:
    n = int(SAMPLE_RATE * duration)
    t = np.linspace(0, duration, n, False)
    freq_t = freq * np.exp(np.log(2) * (glide_cents / 1200) * (t / duration))
    phase = 2 * np.pi * np.cumsum(freq_t) / SAMPLE_RATE
    wave = (amp        * np.sin(phase)
          + amp * 0.35 * np.sin(2 * phase)
          + amp * 0.18 * np.sin(1.5 * phase))
    decay = 14 + 2 * (4 / max(duration, 0.02))
    env = np.exp(-t * decay)
    fade = int(SAMPLE_RATE * 0.003)
    if fade < n: env[:fade] *= np.linspace(0, 1, fade)
    return (wave * env).astype(np.float32)

def _phrase(freqs, total: float = 0.20, amp: float = 0.10) -> np.ndarray:
    n = len(freqs)
    per = total / n
    note_dur = per * 0.85
    gap_dur  = per * 0.15
    gap = np.zeros(int(SAMPLE_RATE * gap_dur), dtype=np.float32)
    parts = []
    for i, f in enumerate(freqs):
        parts.append(_pluck(f, note_dur, amp))
        if i < n - 1: parts.append(gap)
    return np.concatenate(parts)

D5, A5 = 587.33, 880.00
BLIP_START = _phrase([D5, A5], total=0.20, amp=0.10)
BLIP_STOP  = _phrase([A5, D5], total=0.20, amp=0.10)

def play(sound: np.ndarray) -> None:
    if not sound_enabled: return
    try: sd.play(sound, SAMPLE_RATE)
    except Exception as e: log(f"sound error: {e}")

# ---------- system audio mute (pycaw, new API) ----------
def _set_master_mute_sync(muted: bool) -> None:
    try:
        from pycaw.pycaw import AudioUtilities
        device = AudioUtilities.GetSpeakers()
        device.EndpointVolume.SetMute(1 if muted else 0, None)
    except Exception as e:
        log(f"mute({muted}) failed: {e}")

def set_master_mute(muted: bool) -> None:
    threading.Thread(target=_set_master_mute_sync, args=(muted,), daemon=True).start()

def _cleanup_audio_on_exit():
    global muted_by_us
    if muted_by_us:
        try: _set_master_mute_sync(False)
        except Exception: pass
        muted_by_us = False
atexit.register(_cleanup_audio_on_exit)

# ---------- icons ----------
def _mic_icon(color: tuple[int, int, int, int]) -> Image.Image:
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((22, 10, 42, 40), radius=10, fill=color)
    d.rectangle((30, 40, 34, 50), fill=color)
    d.rectangle((22, 50, 42, 54), fill=color)
    return img

ICON_IDLE   = _mic_icon((170, 170, 175, 255))
ICON_REC    = _mic_icon((255, 91, 91, 255))
ICON_BUSY   = _mic_icon((255, 200, 87, 255))
ICON_PAUSED = _mic_icon((105, 105, 110, 255))

# ---------- pill ----------
def init_pill() -> None:
    global pill_win, pill_canvas, pill_dot, pill_text
    pill_win = tk.Toplevel(tk_root)
    pill_win.overrideredirect(True)
    pill_win.attributes("-topmost", True)
    pill_win.wm_attributes("-transparentcolor", TRANSPARENT)
    pill_win.configure(bg=TRANSPARENT)

    W, H = 190, 40
    pill_win.geometry(f"{W}x{H}")
    pill_canvas = tk.Canvas(pill_win, width=W, height=H, bg=TRANSPARENT, highlightthickness=0)
    pill_canvas.pack()
    r = H // 2
    pill_canvas.create_oval(0, 0, H, H, fill=COL_BG, outline="")
    pill_canvas.create_oval(W - H, 0, W, H, fill=COL_BG, outline="")
    pill_canvas.create_rectangle(r, 0, W - r, H, fill=COL_BG, outline="")
    cy = H // 2
    pill_dot  = pill_canvas.create_oval(18, cy - 5, 28, cy + 5, fill=COL_REC, outline="")
    pill_text = pill_canvas.create_text(38, cy, anchor="w", text="Listening",
                                        fill=COL_TEXT, font=("Segoe UI", 11))
    pill_win.withdraw()

def _position_pill() -> None:
    pill_win.update_idletasks()
    sw = pill_win.winfo_screenwidth()
    sh = pill_win.winfo_screenheight()
    w  = pill_win.winfo_width()
    h  = pill_win.winfo_height()
    pill_win.geometry(f"+{(sw - w) // 2}+{sh - h - 90}")

def _refresh_pill() -> None:
    if pill_win is None: return
    if state == "recording":
        pill_canvas.itemconfig(pill_dot, fill=COL_REC)
        pill_canvas.itemconfig(pill_text, text="Listening")
        _position_pill(); pill_win.deiconify()
    elif state == "transcribing":
        pill_canvas.itemconfig(pill_dot, fill=COL_BUSY)
        pill_canvas.itemconfig(pill_text, text="Transcribing…")
        _position_pill(); pill_win.deiconify()
    else:
        pill_win.withdraw()

def flash_pill_warning(msg: str, ms: int = 2800) -> None:
    """Briefly show a warning on the pill, then hide it (unless recording
    resumed meanwhile). Used when a capture comes back silent."""
    if pill_win is None: return
    def _show():
        pill_canvas.itemconfig(pill_dot, fill=COL_BUSY)
        pill_canvas.itemconfig(pill_text, text=msg)
        _position_pill(); pill_win.deiconify()
        def _hide():
            if state not in ("recording", "transcribing"):
                pill_win.withdraw()
        pill_win.after(ms, _hide)
    if tk_root: tk_root.after(0, _show)

# ---------- control window ----------
def _hint_text() -> str:
    name = key_display(HOTKEY)
    if mode == "hold":
        return f"Hold {name} to talk"
    return f"Double-tap {name} to start/stop"

def init_control() -> None:
    global ctrl_status_canvas, ctrl_status_dot_id, ctrl_status_lbl, ctrl_hint_lbl
    global ctrl_toggle_btn, ctrl_mode_var, ctrl_startup_var, ctrl_sound_var
    global ctrl_mute_var, ctrl_words_lbl, ctrl_shortcut_var, ctrl_copied_lbl
    global ctrl_quality_var

    tk_root.title(f"Yapperino v{__version__}")
    tk_root.configure(bg=COL_BG)
    tk_root.geometry("400x720")
    tk_root.resizable(False, False)
    try:
        tk_root._icon_photo = ImageTk.PhotoImage(ICON_REC)
        tk_root.iconphoto(True, tk_root._icon_photo)
    except Exception as e:
        log(f"icon set failed: {e}")

    # status
    status_frame = tk.Frame(tk_root, bg=COL_BG)
    status_frame.pack(pady=(18, 2))
    ctrl_status_canvas = tk.Canvas(status_frame, width=16, height=16,
                                   bg=COL_BG, highlightthickness=0)
    ctrl_status_dot_id = ctrl_status_canvas.create_oval(2, 2, 14, 14,
                                                        fill=COL_REC, outline="")
    ctrl_status_canvas.pack(side="left", padx=(0, 10))
    ctrl_status_lbl = tk.Label(status_frame, text="ACTIVE",
                               fg=COL_TEXT, bg=COL_BG,
                               font=("Segoe UI Semibold", 14))
    ctrl_status_lbl.pack(side="left")

    ctrl_hint_lbl = tk.Label(tk_root, text=_hint_text(),
                             fg=COL_MUTED, bg=COL_BG, font=("Segoe UI", 9))
    ctrl_hint_lbl.pack(pady=(0, 10))

    ctrl_toggle_btn = tk.Button(
        tk_root, text="Pause", width=14, height=1,
        bg=COL_PANEL, fg=COL_TEXT,
        activebackground=COL_PANEL_HI, activeforeground=COL_TEXT,
        borderwidth=0, relief="flat",
        font=("Segoe UI", 10), cursor="hand2",
        command=toggle_paused,
    )
    ctrl_toggle_btn.pack(pady=(0, 12))

    # trigger mode
    mode_frame = tk.Frame(tk_root, bg=COL_BG)
    mode_frame.pack(pady=(0, 6))
    tk.Label(mode_frame, text="Trigger:", fg=COL_MUTED, bg=COL_BG,
             font=("Segoe UI", 9)).pack(side="left", padx=(0, 8))
    ctrl_mode_var = tk.StringVar(value=mode)
    for label, val in [("Hold", "hold"), ("Double-tap", "toggle")]:
        tk.Radiobutton(
            mode_frame, text=label, value=val, variable=ctrl_mode_var,
            command=_apply_mode,
            fg=COL_TEXT, bg=COL_BG, selectcolor=COL_PANEL,
            activeforeground=COL_TEXT, activebackground=COL_BG,
            borderwidth=0, highlightthickness=0,
            font=("Segoe UI", 9), cursor="hand2",
        ).pack(side="left", padx=4)

    # shortcut chooser
    sc_frame = tk.Frame(tk_root, bg=COL_BG)
    sc_frame.pack(pady=(2, 8))
    tk.Label(sc_frame, text="Shortcut:", fg=COL_MUTED, bg=COL_BG,
             font=("Segoe UI", 9)).pack(side="left", padx=(0, 8))
    ctrl_shortcut_var = tk.StringVar(value=key_display(HOTKEY))
    opt = tk.OptionMenu(sc_frame, ctrl_shortcut_var,
                        *[lbl for lbl, _ in SHORTCUT_OPTIONS],
                        command=_apply_shortcut)
    opt.config(bg=COL_PANEL, fg=COL_TEXT, activebackground=COL_PANEL_HI,
               activeforeground=COL_TEXT, borderwidth=0, highlightthickness=0,
               font=("Segoe UI", 9), cursor="hand2", width=18)
    opt["menu"].config(bg=COL_PANEL, fg=COL_TEXT,
                       activebackground=COL_PANEL_HI, activeforeground=COL_TEXT,
                       borderwidth=0)
    opt.pack(side="left")

    # quality chooser (bigger model = fewer mistakes, slightly slower)
    q_frame = tk.Frame(tk_root, bg=COL_BG)
    q_frame.pack(pady=(2, 8))
    tk.Label(q_frame, text="Quality:", fg=COL_MUTED, bg=COL_BG,
             font=("Segoe UI", 9)).pack(side="left", padx=(0, 8))
    ctrl_quality_var = tk.StringVar(value=_QUALITY_BY_MODEL.get(model_name, model_name))
    qopt = tk.OptionMenu(q_frame, ctrl_quality_var,
                         *[lbl for lbl, _ in QUALITY_TIERS],
                         command=_apply_quality)
    qopt.config(bg=COL_PANEL, fg=COL_TEXT, activebackground=COL_PANEL_HI,
                activeforeground=COL_TEXT, borderwidth=0, highlightthickness=0,
                font=("Segoe UI", 9), cursor="hand2", width=20)
    qopt["menu"].config(bg=COL_PANEL, fg=COL_TEXT,
                        activebackground=COL_PANEL_HI, activeforeground=COL_TEXT,
                        borderwidth=0)
    qopt.pack(side="left")

    # checkboxes
    opts_frame = tk.Frame(tk_root, bg=COL_BG)
    opts_frame.pack(pady=(2, 6), fill="x")

    ctrl_startup_var = tk.BooleanVar(value=is_startup_enabled())
    tk.Checkbutton(opts_frame, text="Start with Windows",
                   variable=ctrl_startup_var, command=_apply_startup,
                   fg=COL_TEXT, bg=COL_BG, selectcolor=COL_PANEL,
                   activeforeground=COL_TEXT, activebackground=COL_BG,
                   borderwidth=0, highlightthickness=0,
                   font=("Segoe UI", 10), cursor="hand2",
                   anchor="w").pack(fill="x", padx=24)

    ctrl_sound_var = tk.BooleanVar(value=sound_enabled)
    tk.Checkbutton(opts_frame, text="Play sounds",
                   variable=ctrl_sound_var, command=_apply_sound,
                   fg=COL_TEXT, bg=COL_BG, selectcolor=COL_PANEL,
                   activeforeground=COL_TEXT, activebackground=COL_BG,
                   borderwidth=0, highlightthickness=0,
                   font=("Segoe UI", 10), cursor="hand2",
                   anchor="w").pack(fill="x", padx=24)

    ctrl_mute_var = tk.BooleanVar(value=mute_audio_pref)
    tk.Checkbutton(opts_frame, text="Mute system audio while recording",
                   variable=ctrl_mute_var, command=_apply_mute_pref,
                   fg=COL_TEXT, bg=COL_BG, selectcolor=COL_PANEL,
                   activeforeground=COL_TEXT, activebackground=COL_BG,
                   borderwidth=0, highlightthickness=0,
                   font=("Segoe UI", 10), cursor="hand2",
                   anchor="w").pack(fill="x", padx=24)

    # stats
    ctrl_words_lbl = tk.Label(tk_root,
                              text=f"Words transcribed: {total_words:,}",
                              fg=COL_MUTED, bg=COL_BG, font=("Segoe UI", 9))
    ctrl_words_lbl.pack(pady=(6, 0))

    # history header
    hist_header = tk.Frame(tk_root, bg=COL_BG)
    hist_header.pack(fill="x", padx=20, pady=(10, 2))
    tk.Label(hist_header, text="History  (click to copy)",
             fg=COL_MUTED, bg=COL_BG, font=("Segoe UI", 9)).pack(side="left")
    ctrl_copied_lbl = tk.Label(hist_header, text="",
                               fg=COL_OK, bg=COL_BG, font=("Segoe UI", 9))
    ctrl_copied_lbl.pack(side="right")

    _build_history_widget(tk_root)

    btm = tk.Frame(tk_root, bg=COL_BG)
    btm.pack(side="bottom", fill="x", pady=12, padx=20)
    tk.Button(btm, text="Hide", bg=COL_PANEL, fg=COL_TEXT, borderwidth=0,
              activebackground=COL_PANEL_HI, activeforeground=COL_TEXT,
              font=("Segoe UI", 9), width=8, cursor="hand2",
              command=hide_control).pack(side="left")
    tk.Button(btm, text="Quit", bg=COL_PANEL, fg="#ff8a8a", borderwidth=0,
              activebackground=COL_PANEL_HI, activeforeground="#ff8a8a",
              font=("Segoe UI", 9), width=8, cursor="hand2",
              command=quit_app).pack(side="right")

    tk_root.protocol("WM_DELETE_WINDOW", hide_control)

# ---------- history widget (scrollable Frame with separator lines) ----------
def _build_history_widget(parent) -> None:
    global history_inner, history_canvas
    outer = tk.Frame(parent, bg=COL_BG)
    outer.pack(fill="both", expand=True, padx=20, pady=(0, 8))

    history_canvas = tk.Canvas(outer, bg=COL_PANEL, highlightthickness=0,
                               borderwidth=0)
    scrollbar = tk.Scrollbar(outer, orient="vertical",
                             command=history_canvas.yview,
                             bg=COL_PANEL, troughcolor=COL_BG,
                             activebackground=COL_PANEL_HI,
                             borderwidth=0, highlightthickness=0)
    history_canvas.config(yscrollcommand=scrollbar.set)
    scrollbar.pack(side="right", fill="y")
    history_canvas.pack(side="left", fill="both", expand=True)

    history_inner = tk.Frame(history_canvas, bg=COL_PANEL)
    inner_id = history_canvas.create_window((0, 0), window=history_inner, anchor="nw")

    def _on_inner_config(event):
        history_canvas.config(scrollregion=history_canvas.bbox("all"))
    history_inner.bind("<Configure>", _on_inner_config)

    def _on_canvas_config(event):
        history_canvas.itemconfig(inner_id, width=event.width)
    history_canvas.bind("<Configure>", _on_canvas_config)

    def _on_wheel(event):
        history_canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
    def _bind_wheel(_):
        history_canvas.bind_all("<MouseWheel>", _on_wheel)
    def _unbind_wheel(_):
        history_canvas.unbind_all("<MouseWheel>")
    history_canvas.bind("<Enter>", _bind_wheel)
    history_canvas.bind("<Leave>", _unbind_wheel)

    _refresh_history()

def _make_history_row(parent, full_text: str):
    display = full_text.strip().replace("\n", " ")
    if len(display) > HISTORY_PREVIEW_CHARS:
        display = display[:HISTORY_PREVIEW_CHARS - 1] + "…"

    row = tk.Frame(parent, bg=COL_PANEL)
    lbl = tk.Label(row, text=display, bg=COL_PANEL, fg=COL_TEXT,
                   font=("Segoe UI", 9), anchor="w", justify="left",
                   wraplength=315, padx=10, pady=7, cursor="hand2")
    lbl.pack(fill="x")

    def _enter(_):
        row.config(bg=COL_PANEL_HI); lbl.config(bg=COL_PANEL_HI)
    def _leave(_):
        row.config(bg=COL_PANEL);    lbl.config(bg=COL_PANEL)
    def _click(_):
        try:
            pyperclip.copy(full_text)
            _flash_copied()
        except Exception as e:
            log(f"history copy failed: {e}")

    for w in (row, lbl):
        w.bind("<Enter>", _enter)
        w.bind("<Leave>", _leave)
        w.bind("<Button-1>", _click)
    return row

def _refresh_history() -> None:
    if history_inner is None: return
    for w in history_inner.winfo_children():
        w.destroy()
    if not history:
        empty = tk.Label(history_inner, text="(no transcripts yet)",
                         bg=COL_PANEL, fg=COL_MUTED,
                         font=("Segoe UI", 9, "italic"),
                         padx=10, pady=10)
        empty.pack(fill="x")
        return
    for i, text in enumerate(history):
        row = _make_history_row(history_inner, text)
        row.pack(fill="x")
        if i < len(history) - 1:
            sep = tk.Frame(history_inner, height=1, bg=COL_SEP)
            sep.pack(fill="x")

def show_control() -> None:
    if tk_root is None: return
    tk_root.deiconify()
    tk_root.lift()
    tk_root.attributes("-topmost", True)
    tk_root.after(80, lambda: tk_root.attributes("-topmost", False))

def hide_control() -> None:
    if tk_root is not None: tk_root.withdraw()

def _refresh_control() -> None:
    if ctrl_status_lbl is None: return
    if model_loading:
        ctrl_status_canvas.itemconfig(ctrl_status_dot_id, fill=COL_BUSY)
        ctrl_status_lbl.config(text="LOADING MODEL…", fg=COL_TEXT)
        ctrl_toggle_btn.config(text="Pause")
    elif paused:
        ctrl_status_canvas.itemconfig(ctrl_status_dot_id, fill=COL_IDLE)
        ctrl_status_lbl.config(text="PAUSED", fg=COL_MUTED)
        ctrl_toggle_btn.config(text="Resume")
    else:
        ctrl_toggle_btn.config(text="Pause")
        if state == "recording":
            ctrl_status_canvas.itemconfig(ctrl_status_dot_id, fill=COL_REC)
            ctrl_status_lbl.config(text="LISTENING", fg=COL_TEXT)
        elif state == "transcribing":
            ctrl_status_canvas.itemconfig(ctrl_status_dot_id, fill=COL_BUSY)
            ctrl_status_lbl.config(text="TRANSCRIBING", fg=COL_TEXT)
        else:
            ctrl_status_canvas.itemconfig(ctrl_status_dot_id, fill=COL_REC)
            ctrl_status_lbl.config(text="ACTIVE", fg=COL_TEXT)
    if ctrl_hint_lbl is not None:
        ctrl_hint_lbl.config(text=_hint_text())
    if ctrl_words_lbl is not None:
        ctrl_words_lbl.config(text=f"Words transcribed: {total_words:,}")

def _flash_copied() -> None:
    if ctrl_copied_lbl is None: return
    ctrl_copied_lbl.config(text="Copied ✓")
    tk_root.after(1200, lambda: ctrl_copied_lbl.config(text=""))

def toggle_paused() -> None:
    global paused
    paused = not paused
    log(f"paused={paused}")
    set_state(state)

# ---------- settings apply ----------
def _apply_mode() -> None:
    global mode
    mode = ctrl_mode_var.get()
    log(f"mode={mode}")
    save_config()
    if tk_root: tk_root.after(0, _refresh_control)

def _apply_sound() -> None:
    global sound_enabled
    sound_enabled = ctrl_sound_var.get()
    log(f"sound_enabled={sound_enabled}")
    save_config()

def _apply_mute_pref() -> None:
    global mute_audio_pref
    mute_audio_pref = ctrl_mute_var.get()
    log(f"mute_audio_pref={mute_audio_pref}")
    save_config()

def _apply_shortcut(label: str) -> None:
    global HOTKEY, combo_satisfied
    new_key = _KEY_BY_LABEL.get(label)
    if new_key is None: return
    HOTKEY = new_key
    keys_down.clear()
    combo_satisfied = False
    if recording:
        stop_and_transcribe()
    log(f"shortcut={serialize_hotkey(HOTKEY)}")
    save_config()
    if tk_root: tk_root.after(0, _refresh_control)

def _apply_quality(label: str) -> None:
    new_model = _MODEL_BY_QUALITY.get(label)
    if not new_model or new_model == model_name:
        return
    threading.Thread(target=_reload_model, args=(new_model,), daemon=True).start()

def _reload_model(new_model: str) -> None:
    # Build the new model OUTSIDE busy_lock so dictation stays usable on the
    # old one while it loads; swap under the lock only once it's ready.
    global model, model_name, model_loading
    model_loading = True
    if tk_root: tk_root.after(0, _refresh_control)
    log(f"loading model {new_model}")
    try:
        nm = _new_model(new_model)
    except Exception as e:
        log(f"model {new_model} load failed: {e}")
        model_loading = False
        if tk_root:
            tk_root.after(0, lambda: ctrl_quality_var.set(
                _QUALITY_BY_MODEL.get(model_name, model_name)))
            tk_root.after(0, _refresh_control)
        return
    with busy_lock:
        model = nm
        model_name = new_model
    model_loading = False
    save_config()
    log(f"model ready: {new_model}")
    if tk_root: tk_root.after(0, _refresh_control)

# ---------- startup registry ----------
def _startup_command() -> str:
    if getattr(sys, 'frozen', False):
        return f'"{sys.executable}" --background'
    pyw = sys.executable
    if pyw.lower().endswith("python.exe"):
        pyw = pyw[:-len("python.exe")] + "pythonw.exe"
    return f'"{pyw}" "{os.path.abspath(__file__)}" --background'

def is_startup_enabled() -> bool:
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, REG_RUN_KEY) as key:
            val, _ = winreg.QueryValueEx(key, REG_APP_NAME)
            return bool(val)
    except FileNotFoundError:
        return False
    except Exception:
        return False

def _apply_startup() -> None:
    enabled = ctrl_startup_var.get()
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, REG_RUN_KEY, 0,
                            winreg.KEY_ALL_ACCESS) as key:
            if enabled:
                cmd = _startup_command()
                winreg.SetValueEx(key, REG_APP_NAME, 0, winreg.REG_SZ, cmd)
                log(f"startup enabled: {cmd}")
            else:
                try: winreg.DeleteValue(key, REG_APP_NAME)
                except FileNotFoundError: pass
                log("startup disabled")
    except Exception as e:
        log(f"startup toggle failed: {e}")

# ---------- state plumbing ----------
def set_state(new_state: str) -> None:
    global state
    state = new_state
    if tray is not None:
        if paused:                    tray.icon = ICON_PAUSED
        elif state == "recording":    tray.icon = ICON_REC
        elif state == "transcribing": tray.icon = ICON_BUSY
        else:                         tray.icon = ICON_IDLE
    if tk_root is not None:
        tk_root.after(0, _refresh_pill)
        tk_root.after(0, _refresh_control)

# ---------- audio + transcription ----------
def audio_callback(indata, frames, t, status):
    if recording: audio_q.put(indata.copy())

def start_recording() -> None:
    global recording
    if paused or recording: return
    while not audio_q.empty():
        try: audio_q.get_nowait()
        except queue.Empty: break
    recording = True
    play(BLIP_START)
    set_state("recording")
    if mute_audio_pref:
        def _delayed_mute():
            global muted_by_us
            if recording:
                muted_by_us = True
                set_master_mute(True)
        threading.Timer(0.22, _delayed_mute).start()

def stop_and_transcribe() -> None:
    global recording, muted_by_us, total_sessions
    if not recording: return
    recording = False
    if muted_by_us:
        set_master_mute(False)
        muted_by_us = False
    play(BLIP_STOP)
    chunks = []
    while not audio_q.empty():
        chunks.append(audio_q.get_nowait())
    if not chunks:
        set_state("idle"); return
    audio = np.concatenate(chunks, axis=0).flatten().astype(np.float32)
    if len(audio) < SAMPLE_RATE * MIN_AUDIO_SECONDS:
        set_state("idle"); return
    peak = float(np.max(np.abs(audio))) if audio.size else 0.0
    if peak < SILENCE_PEAK:
        log(f"silent capture (peak={peak:.5f}); mic muted or wrong device")
        set_state("idle")
        flash_pill_warning("No sound. Mic muted?")
        return
    set_state("transcribing")
    total_sessions += 1
    threading.Thread(target=_transcribe_and_paste, args=(audio,), daemon=True).start()

def _transcribe_and_paste(audio: np.ndarray) -> None:
    global total_words, history
    with busy_lock:
        try:
            # Use the full dynamic range; quiet mic input transcribes better.
            peak = float(np.max(np.abs(audio))) if audio.size else 0.0
            if peak > 0:
                audio = (audio * (0.95 / peak)).astype(np.float32)
            segments, _ = model.transcribe(
                audio, language="en",
                beam_size=beam_size,
                vad_filter=True,
                condition_on_previous_text=False,
                hotwords=(vocabulary or None),
            )
            text = "".join(s.text for s in segments).strip()
            if not text: return
            if text.lower().strip(" .!?") in HALLUCINATION_JUNK:
                log(f"dropped hallucination: {text!r}")
                return
            prev = None
            try: prev = pyperclip.paste()
            except Exception: pass
            pyperclip.copy(text)
            time.sleep(0.05)
            kb.press(Key.ctrl); kb.press('v'); kb.release('v'); kb.release(Key.ctrl)
            time.sleep(0.1)
            if prev is not None:
                try: pyperclip.copy(prev)
                except Exception: pass
            total_words += len(text.split())
            history.insert(0, text)
            del history[HISTORY_CAP:]
            save_config()
            log(f"> {text}")
            if tk_root: tk_root.after(0, _refresh_history)
        finally:
            set_state("idle")

# ---------- hotkey (combo-aware) ----------
def on_press(key):
    global combo_satisfied, last_tap_time
    if key not in HOTKEY: return
    keys_down.add(key)
    if not HOTKEY.issubset(keys_down):
        return
    if combo_satisfied:
        return  # OS key-repeat or extra key event while combo already held
    combo_satisfied = True

    if mode == "hold":
        start_recording()
        return

    now = time.time()
    if recording:
        stop_and_transcribe()
    elif now - last_tap_time < DOUBLE_TAP_WINDOW:
        start_recording()
    last_tap_time = now

def on_release(key):
    global combo_satisfied
    if key not in HOTKEY: return
    keys_down.discard(key)
    if combo_satisfied and not HOTKEY.issubset(keys_down):
        combo_satisfied = False
        if mode == "hold":
            stop_and_transcribe()

# ---------- main ----------
def quit_app(*_args) -> None:
    log("quit")
    _cleanup_audio_on_exit()
    save_config()
    if tray is not None:
        try: tray.stop()
        except Exception: pass
    if tk_root is not None:
        try: tk_root.after(0, tk_root.destroy)
        except Exception: pass

def main():
    global tray, tk_root
    tk_root = tk.Tk()

    init_control()
    init_pill()

    stream = sd.InputStream(samplerate=SAMPLE_RATE, channels=1,
                            dtype='float32', callback=audio_callback)
    stream.start()

    tray = pystray.Icon(
        "yapperino", ICON_IDLE, "Yapperino",
        menu=pystray.Menu(
            pystray.MenuItem(
                "Open", lambda *_: tk_root.after(0, show_control), default=True),
            pystray.MenuItem(
                lambda item: "Resume" if paused else "Pause",
                lambda *_: tk_root.after(0, toggle_paused)),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(
                "Quit", lambda *_: tk_root.after(0, quit_app)),
        ),
    )
    threading.Thread(target=tray.run, daemon=True).start()

    listener = keyboard.Listener(on_press=on_press, on_release=on_release)
    listener.start()

    if "--background" in sys.argv:
        hide_control()
    else:
        show_control()

    set_state("idle")

    try:
        tk_root.mainloop()
    finally:
        listener.stop()
        stream.stop()
        _cleanup_audio_on_exit()
        save_config()
        log("exit")

if __name__ == "__main__":
    main()
