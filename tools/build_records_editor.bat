@echo off
REM Requires: python -m pip install pyinstaller
cd /d "%~dp0.."
python -m PyInstaller --noconfirm --onefile --windowed --name "OVRDrive Records Editor" --paths tools --distpath dist --workpath build --specpath build tools\records_editor.py
