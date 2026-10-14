"""Register (or with --uninstall, remove) the native helper for Chrome, Brave, Edge and Chromium.

Only writes to HKEY_CURRENT_USER, so no admin rights are needed.
"""
import json
import sys
import winreg
from pathlib import Path

NAME = "com.ebookgenerator.launcher"
EXTENSION_ID = "odngjaikikekckfpedgnonmacolfgdom"   # fixed by the "key" in extension/manifest.json
HERE = Path(__file__).resolve().parent
MANIFEST = HERE / f"{NAME}.json"

BROWSERS = {
    "Chrome": r"Software\Google\Chrome\NativeMessagingHosts",
    "Brave": r"Software\BraveSoftware\Brave-Browser\NativeMessagingHosts",
    "Edge": r"Software\Microsoft\Edge\NativeMessagingHosts",
    "Chromium": r"Software\Chromium\NativeMessagingHosts",
}


def install():
    MANIFEST.write_text(json.dumps({
        "name": NAME,
        "description": "Starts the Ebook Generator app for the Read Aloud extension",
        "path": str(HERE / "host.bat"),
        "type": "stdio",
        "allowed_origins": [f"chrome-extension://{EXTENSION_ID}/"],
    }, indent=2), encoding="utf-8")
    for browser, key in BROWSERS.items():
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, rf"{key}\{NAME}") as k:
            winreg.SetValueEx(k, "", 0, winreg.REG_SZ, str(MANIFEST))
        print(f"  registered for {browser}")


def uninstall():
    for browser, key in BROWSERS.items():
        try:
            winreg.DeleteKey(winreg.HKEY_CURRENT_USER, rf"{key}\{NAME}")
            print(f"  removed from {browser}")
        except FileNotFoundError:
            pass
    MANIFEST.unlink(missing_ok=True)


if __name__ == "__main__":
    uninstall() if "--uninstall" in sys.argv else install()
