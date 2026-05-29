# Changelog

## v0.2.0 (2026-05-29)

Transcription accuracy upgrade. Still fully local, free, and offline.

- Default model is now `medium.en` instead of `base.en`. Far fewer mistakes, including on names, jargon, and numbers.
- Quality dropdown in the tray window to pick the model live, no restart: Fast (`small.en`), Balanced (`medium.en`), High (`large-v3-turbo`), Max (`large-v3`).
- Custom vocabulary. Set words in config under `vocabulary` so Whisper spells your jargon and product names correctly instead of guessing the nearest word.
- Beam search decoding (beam size 5) for better accuracy.
- Audio is normalized before transcription, which helps a quiet mic.
- Filters out Whisper's silence hallucinations like "thanks for watching".

Models download on first use and are cached under your user profile. Want the original lightweight build with one small model and no extra downloads? Use [v0.1.0](https://github.com/HTouqan/yapperino/releases/tag/v0.1.0).

## v0.1.0 (2026-05-25)

Initial release.
