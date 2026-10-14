@echo off
cd /d "%~dp0"
python native-host\register.py --uninstall
echo  Helper removed. You can now remove the extension from your browser.
pause
