"""
Sound preview for Flow.
Run it, click Start/Stop on each variant, drag the volume slider.
Tell me which variant + volume you want and I'll wire it into flow.py.
All variants are ~200ms total — same duration as the current pair.
"""
import numpy as np
import sounddevice as sd
import tkinter as tk

SAMPLE_RATE = 16000

# notes
D5, E5, F5s, G5, A5, B5, Cs6, D6 = 587.33, 659.25, 739.99, 783.99, 880.00, 987.77, 1108.73, 1174.66

def pluck(freq: float, duration: float, amp: float, glide_cents: float = -22) -> np.ndarray:
    n = int(SAMPLE_RATE * duration)
    t = np.linspace(0, duration, n, False)
    freq_t = freq * np.exp(np.log(2) * (glide_cents / 1200) * (t / duration))
    phase = 2 * np.pi * np.cumsum(freq_t) / SAMPLE_RATE
    wave = (amp        * np.sin(phase)
          + amp * 0.35 * np.sin(2 * phase)
          + amp * 0.18 * np.sin(1.5 * phase))
    decay = 14 + 2 * (4 / max(duration, 0.02))  # faster decay on shorter notes
    env = np.exp(-t * decay)
    fade = int(SAMPLE_RATE * 0.003)
    if fade < n: env[:fade] *= np.linspace(0, 1, fade)
    return (wave * env).astype(np.float32)

def phrase(freqs, total: float = 0.20, amp: float = 0.10) -> np.ndarray:
    n = len(freqs)
    per = total / n
    note_dur = per * 0.85
    gap_dur  = per * 0.15
    gap = np.zeros(int(SAMPLE_RATE * gap_dur), dtype=np.float32)
    parts = []
    for i, f in enumerate(freqs):
        parts.append(pluck(f, note_dur, amp))
        if i < n - 1: parts.append(gap)
    return np.concatenate(parts)

# variants: (label, ascending-note-sequence-for-Start)
VARIANTS = [
    ("V1 — 3 notes  (D F# A)",          [D5, F5s, A5]),
    ("V2 — 4 notes  (D E F# A)",        [D5, E5, F5s, A5]),
    ("V3 — 5 notes  (D E F# G A)",      [D5, E5, F5s, G5, A5]),
    ("V4 — 4 notes wide (D F# A D6)",   [D5, F5s, A5, D6]),
    ("V5 — 5 notes wide (D F# A C# D6)",[D5, F5s, A5, Cs6, D6]),
    ("V6 — current 2 notes (D A)",      [D5, A5]),
]

volume = 0.10

def play_start(freqs):
    sd.play(phrase(freqs, total=0.20, amp=volume), SAMPLE_RATE)

def play_stop(freqs):
    sd.play(phrase(list(reversed(freqs)), total=0.20, amp=volume), SAMPLE_RATE)

# UI
COL_BG = "#1a1a1c"; COL_PANEL = "#26262a"; COL_HI = "#33333a"
COL_TEXT = "#f0f0f2"; COL_MUTED = "#8a8a90"

root = tk.Tk()
root.title("Flow — Sound Preview")
root.configure(bg=COL_BG)
root.geometry("440x460")
root.resizable(False, False)

tk.Label(root, text="Pick the start/stop blip",
         fg=COL_TEXT, bg=COL_BG, font=("Segoe UI Semibold", 13)
         ).pack(pady=(18, 4))
tk.Label(root, text="All variants are ~200ms — same duration as current.",
         fg=COL_MUTED, bg=COL_BG, font=("Segoe UI", 9)
         ).pack(pady=(0, 14))

for label, freqs in VARIANTS:
    row = tk.Frame(root, bg=COL_BG)
    row.pack(fill="x", padx=22, pady=3)
    tk.Label(row, text=label, fg=COL_TEXT, bg=COL_BG,
             font=("Segoe UI", 10), width=30, anchor="w"
             ).pack(side="left")
    tk.Button(row, text="Start", width=6, bg=COL_PANEL, fg=COL_TEXT,
              activebackground=COL_HI, activeforeground=COL_TEXT,
              borderwidth=0, font=("Segoe UI", 9), cursor="hand2",
              command=lambda f=freqs: play_start(f)
              ).pack(side="left", padx=3)
    tk.Button(row, text="Stop", width=6, bg=COL_PANEL, fg=COL_TEXT,
              activebackground=COL_HI, activeforeground=COL_TEXT,
              borderwidth=0, font=("Segoe UI", 9), cursor="hand2",
              command=lambda f=freqs: play_stop(f)
              ).pack(side="left", padx=3)

tk.Label(root, text="Volume", fg=COL_MUTED, bg=COL_BG,
         font=("Segoe UI", 9)).pack(pady=(22, 2))

vol_val_lbl = tk.Label(root, text="0.10", fg=COL_TEXT, bg=COL_BG,
                       font=("Segoe UI", 9))
vol_val_lbl.pack()

def set_vol(v):
    global volume
    volume = float(v)
    vol_val_lbl.config(text=f"{volume:.2f}")

slider = tk.Scale(root, from_=0.02, to=0.25, resolution=0.01,
                  orient="horizontal", bg=COL_BG, fg=COL_TEXT,
                  troughcolor=COL_PANEL, highlightthickness=0,
                  length=320, showvalue=False, command=set_vol)
slider.set(0.10)
slider.pack()

tk.Label(root, text="When you've picked one, tell me the variant # and volume.",
         fg=COL_MUTED, bg=COL_BG, font=("Segoe UI", 8)
         ).pack(pady=(20, 0))

root.mainloop()
