@echo off
echo ============================================
echo   Build Calcolatore Bolletta Luce v2.0.0
echo ============================================
echo.

echo [1/2] Creazione eseguibile con PyInstaller...
python -m PyInstaller CalcoloBolletta.spec --noconfirm
if errorlevel 1 (
    echo ERRORE: PyInstaller ha fallito!
    pause
    exit /b 1
)

echo.
echo [2/2] Creazione installer con Inno Setup...
where iscc >nul 2>&1
if errorlevel 1 (
    echo ATTENZIONE: Inno Setup Compiler (iscc) non trovato nel PATH.
    echo Per creare l'installer, installa Inno Setup da: https://jrsoftware.org/isinfo.php
    echo Poi esegui: iscc CalcoloBolletta_setup.iss
    echo.
    echo L'eseguibile standalone e' comunque disponibile in:
    echo   dist\CalcoloBolletta\CalcoloBolletta.exe
) else (
    iscc CalcoloBolletta_setup.iss
    if errorlevel 1 (
        echo ERRORE: Inno Setup ha fallito!
    ) else (
        echo.
        echo Installer creato in: installer_output\CalcoloBolletta_Setup_v2.0.0.exe
    )
)

echo.
echo Build completata!
pause
