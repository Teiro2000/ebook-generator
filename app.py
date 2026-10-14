"""Ebook Generator - turn a Word document into a narrated audiobook.

Run:  python app.py   (or double-click start.bat)
"""
import argparse
import asyncio
import base64
import io
import os
import re
import socket
import sys
import urllib.request
import threading
import uuid
import webbrowser
import zipfile
from pathlib import Path

import edge_tts
from docx import Document
from flask import Flask, jsonify, request, send_file, send_from_directory

BASE_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = BASE_DIR / "output"
PORT = 5173

# Voices that sound the most natural for long-form narration; shown first in the picker.
RECOMMENDED_VOICES = [
    "en-US-AndrewMultilingualNeural",
    "en-US-AvaMultilingualNeural",
    "en-US-EmmaMultilingualNeural",
    "en-US-BrianMultilingualNeural",
    "en-GB-RyanNeural",
    "en-GB-SoniaNeural",
    "en-AU-WilliamNeural",
    "en-US-ChristopherNeural",
]
DEFAULT_VOICE = RECOMMENDED_VOICES[0]

CHUNK_CHARS = 900          # in-app playback: group paragraphs up to this size
PART_WORDS = 3000          # docs without headings get split into parts of ~this size

app = Flask(__name__, static_folder="static")
books = {}                 # book_id -> parsed book
exports = {}               # job_id -> progress dict
_voice_cache = None


# ---------------------------------------------------------------- parsing

def heading_level(paragraph):
    name = (paragraph.style.name or "").lower() if paragraph.style is not None else ""
    if name == "title":
        return 0
    m = re.match(r"heading\s*(\d)", name)
    return int(m.group(1)) if m else None


def parse_docx(stream, filename):
    doc = Document(stream)
    paras = []
    for p in doc.paragraphs:
        text = re.sub(r"\s+", " ", p.text).strip()
        if text:
            paras.append((text, heading_level(p)))
    return build_book(paras, Path(filename).stem)


PLAIN_HEADING = re.compile(
    r"^(chapter|part|book|section|prologue|epilogue|introduction|preface|foreword|afterword)\b.{0,60}$",
    re.IGNORECASE,
)


def parse_text(raw, title):
    """Pasted text: blank lines or line breaks separate paragraphs; 'Chapter 3'-style lines become headings."""
    paras = []
    for block in re.split(r"\n\s*\n|\r\n\s*\r\n", raw):
        lines = [l.strip() for l in block.splitlines() if l.strip()]
        # A block of short wrapped lines is one paragraph; a block of full lines is several.
        if len(lines) > 1 and all(len(l) < 90 for l in lines[:-1]) and not any(PLAIN_HEADING.match(l) for l in lines):
            lines = [" ".join(lines)]
        for line in lines:
            text = re.sub(r"\s+", " ", line)
            paras.append((text, 1 if PLAIN_HEADING.match(text) else None))
    return build_book(paras, title)


def build_book(paras, title):
    """paras: list of (text, heading_level_or_None)."""
    levels = [lvl for _, lvl in paras if lvl is not None and lvl > 0]
    split_level = min(levels) if levels else None

    chapters = []
    current = None
    for text, lvl in paras:
        starts_chapter = split_level is not None and lvl is not None and 0 < lvl <= split_level
        if current is None or starts_chapter:
            # Text before the first heading is named after the document itself.
            current = {"title": text if starts_chapter else title, "paragraphs": []}
            chapters.append(current)
        current["paragraphs"].append({"text": text, "heading": lvl is not None})

    if split_level is None and chapters:
        # No headings: break into evenly sized parts so navigation still works.
        all_paras = chapters[0]["paragraphs"]
        chapters, words = [], 0
        for p in all_paras:
            if not chapters or words >= PART_WORDS:
                chapters.append({"title": "", "paragraphs": []})
                words = 0
            chapters[-1]["paragraphs"].append(p)
            words += len(p["text"].split())
        for i, ch in enumerate(chapters):
            ch["title"] = title if len(chapters) == 1 else f"{title} - Part {i + 1}"

    for ch in chapters:
        ch["chunks"] = make_chunks(ch["paragraphs"])

    return {"title": title, "chapters": chapters}


def make_chunks(paragraphs):
    """Group consecutive paragraphs into playback chunks: [start, end] inclusive."""
    chunks, start, size = [], 0, 0
    for i, p in enumerate(paragraphs):
        if i > start and (size + len(p["text"]) > CHUNK_CHARS or p["heading"]):
            chunks.append([start, i - 1])
            start, size = i, 0
        size += len(p["text"])
        if p["heading"]:
            # Headings get their own chunk so there's a natural pause after them.
            chunks.append([start, i])
            start, size = i + 1, 0
    if start < len(paragraphs):
        chunks.append([start, len(paragraphs) - 1])
    return chunks


def chapter_text(chapter, start=0, end=None):
    paras = chapter["paragraphs"][start:(end + 1 if end is not None else None)]
    parts = []
    for p in paras:
        t = p["text"]
        # Make sure headings and lines without punctuation still get a pause.
        if not re.search(r"[.!?:;\"')\]]$", t):
            t += "."
        parts.append(t)
    return "\n\n".join(parts)


# ---------------------------------------------------------------- speech

async def _synthesize(text, voice, rate="+0%"):
    buf = bytearray()
    async for chunk in edge_tts.Communicate(text, voice, rate=rate).stream():
        if chunk["type"] == "audio":
            buf.extend(chunk["data"])
    return bytes(buf)


def synthesize(text, voice, rate="+0%"):
    return asyncio.run(_synthesize(text, voice, rate))


async def _synthesize_with_words(text, voice, rate):
    audio, boundaries = bytearray(), []
    async for chunk in edge_tts.Communicate(text, voice, rate=rate, boundary="WordBoundary").stream():
        if chunk["type"] == "audio":
            audio.extend(chunk["data"])
        elif chunk["type"] == "WordBoundary":
            boundaries.append(chunk)
    return bytes(audio), boundaries


def synthesize_with_words(text, voice, rate="+0%"):
    """Audio plus word timings mapped back to character positions in `text`."""
    audio, boundaries = asyncio.run(_synthesize_with_words(text, voice, rate))
    words, cursor, lower = [], 0, text.lower()
    for b in boundaries:
        word = b["text"]
        i = text.find(word, cursor)
        if i < 0:
            i = lower.find(word.lower(), cursor)
        if i < 0 or i - cursor > 200:   # couldn't place it (e.g. normalised text); keep timing order intact
            continue
        words.append({
            "start": b["offset"] / 10_000,                     # 100ns ticks -> ms
            "end": (b["offset"] + b["duration"]) / 10_000,
            "index": i,
            "length": len(word),
        })
        cursor = i + len(word)
    return audio, words


def rate_string(speed):
    pct = round((float(speed) - 1.0) * 100)
    return f"{pct:+d}%"


def safe_name(s, limit=60):
    s = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "", s).strip().rstrip(".")
    return (s[:limit].strip() or "Untitled")


# ---------------------------------------------------------------- routes

@app.get("/")
def index():
    return send_from_directory(app.static_folder, "index.html")


@app.get("/api/ping")
def ping():
    return jsonify({"app": "ebook-generator", "ok": True})


@app.post("/api/read")
def read_selection():
    """Used by the browser extension: speak a piece of text and report when each word is said."""
    data = request.get_json(silent=True)
    if not data or not data.get("text", "").strip():
        return jsonify({"error": "No text"}), 400
    try:
        audio, words = synthesize_with_words(
            data["text"][:5000], data.get("voice") or DEFAULT_VOICE, rate_string(data.get("speed", 1.0)))
    except Exception as e:
        return jsonify({"error": f"Voice service error: {e}"}), 502
    return jsonify({"audio": base64.b64encode(audio).decode(), "words": words})


@app.post("/api/shutdown")
def shutdown():
    # get_json(silent=False) rejects non-JSON posts, so ordinary web pages can't trigger this.
    request.get_json()
    threading.Timer(0.3, lambda: os._exit(0)).start()
    return jsonify({"ok": True})


@app.get("/api/voices")
def voices():
    global _voice_cache
    if _voice_cache is None:
        all_voices = asyncio.run(edge_tts.list_voices())
        english = [v for v in all_voices if v["Locale"].startswith("en-")]
        rank = {name: i for i, name in enumerate(RECOMMENDED_VOICES)}
        english.sort(key=lambda v: (rank.get(v["ShortName"], 999), v["Locale"], v["ShortName"]))
        _voice_cache = [
            {
                "id": v["ShortName"],
                "name": v["ShortName"].split("-")[-1].replace("Neural", "").replace("Multilingual", " (multilingual)"),
                "locale": v["Locale"],
                "gender": v["Gender"],
                "recommended": v["ShortName"] in rank,
            }
            for v in english
        ]
    return jsonify({"voices": _voice_cache, "default": DEFAULT_VOICE})


@app.post("/api/upload")
def upload():
    f = request.files.get("file")
    if not f or not f.filename.lower().endswith(".docx"):
        return jsonify({"error": "Please choose a .docx Word file."}), 400
    try:
        book = parse_docx(io.BytesIO(f.read()), f.filename)
    except Exception as e:
        return jsonify({"error": f"Couldn't read that document: {e}"}), 400
    return add_book(book, request.form.get("append"))


@app.post("/api/text")
def paste_text():
    data = request.get_json() or {}
    title = safe_name(data.get("title") or "Pasted text")
    return add_book(parse_text(data.get("text", ""), title), data.get("append"))


def add_book(book, append_to=None):
    """Store a new book, or add its chapters to the end of an already-open one."""
    if not book["chapters"]:
        return jsonify({"error": "There doesn't seem to be any text to read."}), 400
    if append_to:
        existing = books.get(append_to)
        if not existing:
            return jsonify({"error": "The open book was lost (app restarted?) - click New book and start again."}), 404
        existing["chapters"].extend(book["chapters"])
        return jsonify({"id": append_to, "added": len(book["chapters"]), **existing})
    book_id = uuid.uuid4().hex
    books[book_id] = book
    return jsonify({"id": book_id, **book})


@app.get("/api/speak")
def speak():
    book = books.get(request.args.get("book", ""))
    if not book:
        return jsonify({"error": "Document not loaded - please upload it again."}), 404
    ch = book["chapters"][int(request.args["chapter"])]
    start, end = ch["chunks"][int(request.args["chunk"])]
    voice = request.args.get("voice", DEFAULT_VOICE)
    try:
        audio = synthesize(chapter_text(ch, start, end), voice)
    except Exception as e:
        return jsonify({"error": f"Voice service error: {e}"}), 502
    return send_file(io.BytesIO(audio), mimetype="audio/mpeg")


@app.get("/api/preview")
def preview():
    voice = request.args.get("voice", DEFAULT_VOICE)
    text = "Hello! This is how I'll sound reading your book. Sit back, relax, and enjoy the story."
    return send_file(io.BytesIO(synthesize(text, voice)), mimetype="audio/mpeg")


@app.post("/api/export")
def export():
    data = request.get_json()
    book = books.get(data.get("book", ""))
    if not book:
        return jsonify({"error": "Document not loaded - please upload it again."}), 404
    voice = data.get("voice", DEFAULT_VOICE)
    rate = rate_string(data.get("speed", 1.0))
    selected = data.get("chapters") or list(range(len(book["chapters"])))

    job_id = uuid.uuid4().hex
    folder = OUTPUT_DIR / safe_name(book["title"])
    job = {"done": 0, "total": len(selected), "current": "", "finished": False,
           "error": None, "files": [], "folder": str(folder)}
    exports[job_id] = job

    def run():
        try:
            folder.mkdir(parents=True, exist_ok=True)
            width = max(2, len(str(len(book["chapters"]))))
            for idx in selected:
                ch = book["chapters"][idx]
                job["current"] = ch["title"]
                audio = synthesize(chapter_text(ch), voice, rate)
                path = folder / f"{str(idx + 1).zfill(width)} - {safe_name(ch['title'])}.mp3"
                path.write_bytes(audio)
                job["files"].append(str(path))
                job["done"] += 1
        except Exception as e:
            job["error"] = str(e)
        finally:
            job["finished"] = True

    threading.Thread(target=run, daemon=True).start()
    return jsonify({"job": job_id})


@app.get("/api/export/<job_id>")
def export_status(job_id):
    job = exports.get(job_id)
    if not job:
        return jsonify({"error": "Unknown export"}), 404
    return jsonify(job)


@app.get("/api/export/<job_id>/zip")
def export_zip(job_id):
    job = exports.get(job_id)
    if not job or not job["files"]:
        return jsonify({"error": "Nothing exported yet"}), 404
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_STORED) as z:
        for f in job["files"]:
            z.write(f, Path(f).name)
    buf.seek(0)
    return send_file(buf, mimetype="application/zip", as_attachment=True,
                     download_name=f"{Path(job['folder']).name} (audiobook).zip")


@app.post("/api/open-folder")
def open_folder():
    folder = Path(request.get_json().get("folder", ""))
    if folder.is_dir() and OUTPUT_DIR in folder.parents:
        os.startfile(folder)
    return jsonify({"ok": True})


def already_running():
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{PORT}/api/ping", timeout=1) as r:
            return b"ebook-generator" in r.read()
    except OSError:
        return False


def port_in_use():
    # Flask's server sets SO_REUSEADDR, which on Windows lets a second copy bind the same port
    # silently. An exclusive bind tells us for sure whether something already owns it.
    s = socket.socket()
    if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
        s.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
    try:
        s.bind(("127.0.0.1", PORT))
        return False
    except OSError:
        return True
    finally:
        s.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--background", action="store_true",
                        help="run hidden for the browser extension (no browser tab, output to a log file)")
    args = parser.parse_args()
    url = f"http://localhost:{PORT}"

    if already_running():
        # e.g. the extension already started it in the background - just show the app.
        if not args.background:
            print(f"\n  Ebook Generator is already running - opening {url}\n")
            webbrowser.open(url)
        sys.exit(0)
    if port_in_use():
        print(f"\n  Port {PORT} is already in use - probably an older Ebook Generator window.\n"
              f"  Close it and try again.\n")
        sys.exit(1)

    if args.background:
        log = open(BASE_DIR / "ebook-generator.log", "w", buffering=1, encoding="utf-8")
        sys.stdout = sys.stderr = log
    else:
        print(f"\n  Ebook Generator running at {url}\n  Close this window to stop it.\n")
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    app.run(host="127.0.0.1", port=PORT, debug=False, threaded=True)
