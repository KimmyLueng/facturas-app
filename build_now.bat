@echo off
cd /d C:\Users\scark\Desktop\facturas_app
python -m PyInstaller --clean --noconfirm GestionFacturas.spec
echo BUILD_EXIT=%ERRORLEVEL% > "%TEMP%\build_done.log"
