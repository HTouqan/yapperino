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

First launch downloads the default speech model (medium, ~1.5 GB). Internet required once, then fully offline. Want a smaller download? See [Models and speed](#models-and-speed) below, or use the lightweight [v0.1.0](https://github.com/HTouqan/yapperino/releases/tag/v0.1.0).

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

## Models and speed

Yapperino runs the Whisper speech model on your **CPU**. It does not use your GPU unless you have an NVIDIA card with CUDA set up. AMD and Intel GPUs are not used for this. Bigger models are more accurate but take longer per dictation on CPU. They all still work without a GPU, they just take more time.

Pick the model in the app from the **Quality** dropdown in the tray window. No need to edit code. Selecting a tier the first time downloads that model once, then it runs offline.

| Quality | Model | Download | Notes |
|---------|-------|----------|-------|
| Fast | `small.en` | ~0.5 GB | Big jump over the old default, very quick |
| Balanced | `medium.en` | ~1.5 GB | Default. Accurate and still fast |
| High | `large-v3-turbo` | ~1.6 GB | `large-v3` quality, pruned to stay quick |
| Max | `large-v3` | ~3 GB | Most accurate, noticeably slower per dictation |

On a strong desktop CPU all four are comfortably faster than real time. On a slow or old CPU, stay on Fast. There is no NVIDIA GPU benefit unless CUDA is installed.

Each model downloads on first use and is cached under your user profile. **If you do not want the larger downloads, use the original lightweight build:** [v0.1.0](https://github.com/HTouqan/yapperino/releases/tag/v0.1.0) ships one small model (~150 MB) and nothing else.

### Custom words

Whisper guesses the nearest normal word for names and jargon it has never seen ("traffic" for Traefik, "image" for immich). Fix this by listing your words in `%LOCALAPPDATA%\Yapperino\config.json` under `vocabulary`, comma separated. Yapperino biases transcription toward those spellings.

For non-English, set a non-`.en` model in config (for example `medium` or `large-v3`).

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
