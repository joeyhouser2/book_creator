@echo off
rem book_creator — what the desktop shortcut runs.
rem
rem Picks an interpreter that can actually do everything: the TTS virtualenv
rem first, because narration lives only there (its torch pin would displace the
rem CUDA build the aligner needs, so it is deliberately kept separate). Falling
rem back to a plain python still gives a working app with the audiobook panel
rem disabled, which is better than refusing to start.

cd /d "%~dp0"
title book_creator server

set "PY="
if exist ".venv-tts\Scripts\python.exe" set "PY=.venv-tts\Scripts\python.exe"
if not defined PY if exist ".venv\Scripts\python.exe" set "PY=.venv\Scripts\python.exe"
if not defined PY if exist "venv\Scripts\python.exe" set "PY=venv\Scripts\python.exe"
if not defined PY set "PY=python"

echo Starting book_creator with %PY% ...
echo Close this window to stop the server.
echo.

"%PY%" run_web.py --open %*

rem Only pause on a failure: a clean shutdown (the user closing the window or
rem pressing Ctrl-C) should not leave a stray "press any key" behind, but a
rem crash on startup must stay readable instead of vanishing.
if errorlevel 1 (
  echo.
  echo book_creator exited with an error ^(code %errorlevel%^).
  pause
)
