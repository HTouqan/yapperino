# Yapperino

**Hold to talk. Release to type.**

Free, local voice-to-text for Windows. Speak into your mic, and your words appear in any app you have open. Editors, browsers, chat windows, terminals, anywhere you can type.

Built for people who think faster than they type and don't want a subscription to talk into a microphone.

- Runs entirely on your machine
- No accounts, no cloud, no telemetry
- Works offline after the first launch
- Single .exe, no installer

## Get it

Download `Yapperino.exe` from the [latest release](https://github.com/HTouqan/yapperino/releases/latest).

Double-click to run. Windows SmartScreen will warn that the file is unsigned. Click `More info` then `Run anyway`. (Signing costs a few hundred dollars a year and this is free.)

First launch downloads the speech model (~150 MB). Internet required once. Fully offline after that.

## How to use

Default shortcut is **Right Ctrl**. Hold it, speak, release. The transcription pastes into whatever app has focus.

That's the whole interaction. Open the tray icon to change anything: shortcut, mode, history, mute behaviour.

## Features

- Two trigger modes: hold-to-talk, or double-tap-to-toggle
- 12 shortcut presets, including combos like Left Ctrl + Win or Right Ctrl + Shift
- Mute your speakers automatically while recording, so videos and streams don't bleed into the mic
- History panel: your last 50 transcripts, click any row to copy
- Tray icon with live state colors (idle, recording, transcribing, paused)
- Floating recording pill at the bottom of the screen
- Word counter
- Start with Windows
- Settings persist to `%LOCALAPPDATA%\Yapperino\config.json`

## Privacy

Everything runs locally. Your audio never leaves your machine. Transcripts are saved in plaintext at `%LOCALAPPDATA%\Yapperino\config.json` so the history persists across launches. Anyone with file access to your computer can read them.

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

Output is `dist/Yapperino.exe`. First launch unpacks the bundle to a temp folder (5-10 seconds).

## Whisper model

Defaults to `base.en` (English-only, ~150 MB, fast on CPU).

To use a bigger model, edit `MODEL_NAME` at the top of `yapperino.py`:

| Model | Size | Notes |
|-------|------|-------|
| `tiny.en` | 75 MB | Fastest, lower accuracy |
| `base.en` | 150 MB | Default. Good tradeoff on CPU |
| `small.en` | 460 MB | More accurate, slower on CPU |
| `medium.en` | 1.5 GB | Better. Needs a fast CPU or a GPU |
| `large-v3` | 3 GB | Multilingual, highest accuracy |

For non-English, drop the `.en` suffix.

## License

MIT. See [LICENSE](LICENSE).

## Credits

Built on the work of:

- [openai/whisper](https://github.com/openai/whisper) (the speech model)
- [faster-whisper](https://github.com/SYSTRAN/faster-whisper) (efficient inference via CTranslate2)
- [Silero VAD](https://github.com/snakers4/silero-vad) (voice activity detection)
- [pynput](https://github.com/moses-palmer/pynput) (global hotkey listener)
- [pystray](https://github.com/moses-palmer/pystray) (system tray)
- [pycaw](https://github.com/AndreMiras/pycaw) (Windows audio control)
- [sounddevice](https://github.com/spatialaudio/python-sounddevice), [Pillow](https://github.com/python-pillow/Pillow), [pyperclip](https://github.com/asweigart/pyperclip), [PyInstaller](https://github.com/pyinstaller/pyinstaller)
