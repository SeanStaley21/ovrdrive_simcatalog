@echo off
rem Builds tools\dist\log_best_laps.exe (needs: pip install pyinstaller).
rem ac_id_map.json is copied next to the exe so ids can be added without a rebuild.
cd /d "%~dp0"
py -m PyInstaller --onefile --noconfirm --name log_best_laps --distpath dist --workpath build --specpath build log_best_laps.py
if errorlevel 1 exit /b 1
copy /y ac_id_map.json dist\ac_id_map.json
