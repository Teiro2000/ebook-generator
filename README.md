# Ebook Generator

Turn a Word document (or pasted text) into a narrated audiobook using Microsoft's natural-sounding neural voices.

## Features

- **Open a `.docx`** or **paste text** — chapters are detected from Word headings, or from lines like "Chapter 3" / "Prologue" in pasted text
- **Listen in the app** — the current paragraph is highlighted; click any paragraph to start reading from there
- **Pick a voice** from ~47 English neural voices (with preview) and adjust playback speed
- **Remembers your place** in each book
- **Export MP3s** — one file per chapter, saved to `output/` or downloaded as a `.zip`

## Getting started

Requires [Python 3.10+](https://www.python.org/downloads/) and an internet connection.

**Windows:** double-click `start.bat`. It installs the dependencies on first run and opens the app in your browser.

**Any platform:**

```bash
pip install -r requirements.txt
python app.py
```

Then open http://localhost:5173.

Keyboard shortcuts: <kbd>Space</kbd> play/pause, <kbd>←</kbd>/<kbd>→</kbd> previous/next paragraph.

## How it works

`app.py` is a small Flask server that parses documents with [python-docx](https://python-docx.readthedocs.io/) and generates speech with [edge-tts](https://github.com/rany2/edge-tts) (Microsoft Edge's free online voices). The interface is a single page in `static/index.html`.

## Troubleshooting

**"Voice service error: 403"** — Microsoft occasionally changes the free voice service, which temporarily breaks `edge-tts` until a new version is released. `start.bat` updates it automatically on each launch; otherwise run:

```bash
pip install -U edge-tts
```

and restart the app.
