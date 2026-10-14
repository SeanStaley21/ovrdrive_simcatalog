@echo off
REM Requires: python -m pip install pyinstaller
cd /d "%~dp0.."
python -m PyInstaller --noconfirm --onefile --windowed --icon "%~dp0records_editor.ico" --add-data "%~dp0records_editor.ico;." --name "OVRDrive Records Editor" --paths tools --distpath dist --workpath build --specpath build tools\records_editor.py
