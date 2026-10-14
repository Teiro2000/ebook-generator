@echo off
title Read Aloud extension setup
cd /d "%~dp0"
echo.
echo  Setting up the Read Aloud helper...
echo.
python -m pip install -q -r ..\requirements.txt
python native-host\register.py || goto :error
echo.
echo  Done! Next, load the extension in your browser:
echo    1. Open brave://extensions  (or chrome://extensions)
echo    2. Turn on "Developer mode" (top right)
echo    3. Click "Load unpacked" and choose this folder:
echo       %~dp0
echo.
echo  If you move the Ebook Generator folder, run this again.
echo.
pause
exit /b 0

:error
echo.
echo  Setup failed - see the message above.
pause
exit /b 1
