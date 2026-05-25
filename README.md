# Yapperino

Local voice-to-text for Windows. Hold a key, talk, release. Transcribed text appears in whatever window you had focused.

Free alternative to paid dictation tools. Runs fully offline after the first launch. No accounts, no cloud, no telemetry.

## Get it

Download `Yapperino.exe` from the [latest release](https://github.com/HTouqan/yapperino/releases/latest). Single file. Double-click to run.

Windows SmartScreen will warn that the file is unsigned. Click "More info" then "Run anyway".

First launch downloads the Whisper model (~150 MB) to `~/.cache/huggingface/`. Internet is required once. After that it runs fully offline.

## How to use

Default shortcut is Right Ctrl. Hold it, talk, release. The transcription pastes into whatever app has focus.

Open the control window from the tray icon to change anything.

## Features

- Hold-to-talk or double-tap-to-toggle
- 12 shortcut options including combos: Left Ctrl + Win (Wispr-style), Right Ctrl + Win, Left/Right Alt + Win, Right Ctrl + Shift, Right Ctrl + Alt, plus single right-side modifiers
- Floating pill at the bottom of the screen while recording
- Tray icon with state colors (gray idle, red recording, amber transcribing, dim when paused)
- Optional mute of all system audio during recording so videos and streams stop bleeding into the mic
- History of the last 50 transcripts, click any row to copy
- Word counter
- Start with Windows option
- Settings persist to `%LOCALAPPDATA%\Yapperino\config.json`

## Privacy

Everything runs locally on your machine. Audio is never saved. Transcripts are saved in plaintext in `%LOCALAPPDATA%\Yapperino\config.json` so the history list survives restarts. If you share a machine, anyone with file access can read them.

## Build from source

Requires Python 3.12+ on Windows.

```
git clone https://github.com/HTouqan/yapperino.git
cd yapperino
pip install -r requirements.txt
python yapperino.py
```

Bundle to a single .exe:

```
pip install pyinstaller
python -m PyInstaller --onefile --noconsole --name Yapperino --icon yapperino.ico ^
  --collect-all faster_whisper --collect-all ctranslate2 ^
  --collect-all av --collect-all onnxruntime ^
  --collect-all tokenizers --collect-all pycaw ^
  --collect-all comtypes yapperino.py
```

Output is `dist/Yapperino.exe`. First launch unpacks the bundle to a temp folder, which adds 5-10 seconds.

## Whisper model

Defaults to `base.en` (English-only, ~150 MB). Fast on CPU.

To use a bigger model edit `MODEL_NAME` at the top of `yapperino.py`. Options:

| Model | Size | Notes |
|-------|------|-------|
| `tiny.en` | 75 MB | Fastest, lower accuracy |
| `base.en` | 150 MB | Default. Good tradeoff on CPU |
| `small.en` | 460 MB | More accurate, slower on CPU |
| `medium.en` | 1.5 GB | Better accuracy. Needs a fast CPU or GPU |
| `large-v3` | 3 GB | Multilingual, highest accuracy |

For non-English, drop the `.en` suffix.

## License

MIT. See [LICENSE](LICENSE).

## Credits

- [openai/whisper](https://github.com/openai/whisper) — the speech model
- [faster-whisper](https://github.com/SYSTRAN/faster-whisper) — efficient inference via CTranslate2
- [Silero VAD](https://github.com/snakers4/silero-vad) — voice activity detection
- [pynput](https://github.com/moses-palmer/pynput) — global hotkey listener
- [pystray](https://github.com/moses-palmer/pystray) — system tray icon
- [pycaw](https://github.com/AndreMiras/pycaw) — Windows audio control
- [sounddevice](https://github.com/spatialaudio/python-sounddevice), [Pillow](https://github.com/python-pillow/Pillow), [pyperclip](https://github.com/asweigart/pyperclip), [PyInstaller](https://github.com/pyinstaller/pyinstaller)
