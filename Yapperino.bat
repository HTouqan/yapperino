@echo off
REM Run Yapperino from source - uses pythonw to suppress console.
start "" pythonw.exe "%~dp0yapperino.py" %*
