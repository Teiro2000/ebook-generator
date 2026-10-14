"""Native messaging helper: lets the browser extension start the Ebook Generator app in the background.

Chrome/Brave launch this on demand (see register.py). It speaks the native messaging protocol:
each message is a 4-byte little-endian length followed by JSON.
"""
import json
import socket
import struct
import subprocess
import sys
import urllib.request
from pathlib import Path

APP = Path(__file__).resolve().parents[2] / "app.py"
PING = "http://127.0.0.1:5173/api/ping"


def read_message():
    raw = sys.stdin.buffer.read(4)
    if len(raw) < 4:
        return None
    (length,) = struct.unpack("<I", raw)
    return json.loads(sys.stdin.buffer.read(length))


def send_message(obj):
    data = json.dumps(obj).encode()
    sys.stdout.buffer.write(struct.pack("<I", len(data)) + data)
    sys.stdout.buffer.flush()


def app_running():
    try:
        with urllib.request.urlopen(PING, timeout=1) as r:
            return b"ebook-generator" in r.read()
    except OSError:
        return False


def port_in_use():
    s = socket.socket()
    s.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
    try:
        s.bind(("127.0.0.1", 5173))
        return False
    except OSError:
        return True
    finally:
        s.close()


def start_app():
    pythonw = Path(sys.executable).with_name("pythonw.exe")
    cmd = [str(pythonw if pythonw.exists() else sys.executable), str(APP), "--background"]
    base = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
    common = dict(cwd=str(APP.parent), stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                  stderr=subprocess.DEVNULL, close_fds=True)
    try:
        # The browser runs this helper inside a job object; break away so the app outlives the helper.
        subprocess.Popen(cmd, creationflags=base | subprocess.CREATE_BREAKAWAY_FROM_JOB, **common)
        return "breakaway"
    except OSError:
        pass
    # Breakaway not allowed: have Windows (WMI) start it, which places it outside the browser's job.
    command_line = subprocess.list2cmdline(cmd).replace("'", "''")
    subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-WindowStyle", "Hidden", "-Command",
         f"Invoke-CimMethod -ClassName Win32_Process -MethodName Create "
         f"-Arguments @{{CommandLine='{command_line}'; CurrentDirectory='{APP.parent}'}} | Out-Null"],
        creationflags=subprocess.CREATE_NO_WINDOW, timeout=20, **common)
    return "wmi"


def main():
    msg = read_message() or {}
    if msg.get("action") != "start":
        send_message({"ok": False, "error": "unknown action"})
        return
    if app_running():
        send_message({"ok": True, "already": True})
        return
    if port_in_use():
        send_message({"ok": False, "error": "Port 5173 is in use by something else - probably an older "
                                            "Ebook Generator window. Close it and try again."})
        return
    try:
        send_message({"ok": True, "method": start_app()})
    except Exception as e:
        send_message({"ok": False, "error": str(e)})


if __name__ == "__main__":
    main()
