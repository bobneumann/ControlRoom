@echo off
echo Installing dependencies...
py -m pip install -r requirements.txt
py -m pip install pyinstaller

echo.
echo Building standalone executable...
py -m PyInstaller ^
    --onefile ^
    --windowed ^
    --name InstrumentPanel ^
    --add-data "hosts.json.example;." ^
    designer.py

echo.
if exist dist\InstrumentPanel.exe (
    echo BUILD SUCCESSFUL
    echo Output: dist\InstrumentPanel.exe
    echo.
    echo Copy dist\InstrumentPanel.exe to the target machine.
    echo Copy hosts.json.example alongside it, rename to hosts.json, and configure.
) else (
    echo BUILD FAILED — check output above
)
pause
