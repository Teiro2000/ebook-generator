@echo off
title Ebook Generator
cd /d "%~dp0"
python -c "import flask, docx, edge_tts" 2>nul || (
  echo Installing required packages, one moment...
  python -m pip install -r requirements.txt
)
rem Microsoft occasionally changes the free voice service; staying on the latest edge-tts keeps it working.
python -m pip install -q -U edge-tts 2>nul
python app.py
pause
