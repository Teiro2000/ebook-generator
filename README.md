# Ebook Generator

Turn a Word document (or pasted text) into a narrated audiobook using Microsoft's natural-sounding neural voices.

## Features

- **Open a `.docx`** or **paste text** — chapters are detected from Word headings, or from lines like "Chapter 3" / "Prologue" in pasted text
- **Combine several sources** — with a book open, *Add Word file* / *Add text* appends them as new chapters (you can also select or drop multiple files at once); *New book* starts over
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

## Read Aloud browser extension

Highlight text on any web page and press **F2** (or right-click → **Read aloud**) to hear it in the same neural voice, with each word highlighted as it's spoken. Press F2 again or <kbd>Esc</kbd> to stop.

Works in Chrome, Brave and Edge on Windows. The extension uses the Ebook Generator app for its voice and starts it hidden in the background when needed, so you don't have to launch anything yourself.

**Setup (once):**

1. Double-click `extension/install.bat`. It registers a small helper that lets the browser start the app. Only your user registry is changed; no admin rights are needed.
2. Open `brave://extensions` (or `chrome://extensions`), turn on **Developer mode**, click **Load unpacked** and choose the `extension` folder.

Click the extension's toolbar icon to choose the voice, speed and hotkey (F2–F12), or to stop the background app. `Alt+Shift+R` also works as a backup shortcut.

If Microsoft's voice service is down, the extension falls back to your browser's built-in voice so it still reads.

If you move the folder, run `install.bat` again. To remove the helper, run `extension/uninstall.bat`.

## How it works

`app.py` is a small Flask server that parses documents with [python-docx](https://python-docx.readthedocs.io/) and generates speech with [edge-tts](https://github.com/rany2/edge-tts) (Microsoft Edge's free online voices). The interface is a single page in `static/index.html`.

## Troubleshooting

**"Voice service error: 403"** — Microsoft occasionally changes the free voice service, which temporarily breaks `edge-tts` until a new version is released. `start.bat` updates it automatically on each launch; otherwise run:

```bash
pip install -U edge-tts
```

and restart the app.
