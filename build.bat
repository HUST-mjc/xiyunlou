@echo off
chcp 65001 >nul
echo ========================================
echo Xiyunlou - Build Script
echo ========================================
echo.

REM Check if pyinstaller is installed
pip show pyinstaller >nul 2>&1
if errorlevel 1 (
    echo Installing PyInstaller...
    pip install pyinstaller
)

echo Cleaning old build files...
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist

echo.
echo ========================================
echo Step 1/2: Building updater_new.exe...
echo ========================================
pyinstaller updater.spec --clean

if errorlevel 1 (
    echo.
    echo [ERROR] Updater packaging failed!
    pause
    exit /b 1
)
echo [OK] Updater built successfully

echo.
echo ========================================
echo Step 2/2: Building main program...
echo ========================================
pyinstaller build.spec --clean

if errorlevel 1 (
    echo.
    echo [ERROR] Main program packaging failed!
    pause
    exit /b 1
)
echo [OK] Main program built successfully

echo.
echo Organizing files...

REM Copy updater_new.exe into main folder
if exist dist\updater_new.exe (
    copy /Y dist\updater_new.exe dist\ >nul
    echo [OK] updater_new.exe ready
)

REM Copy img folder
if exist img (
    if not exist dist\img mkdir dist\img
    xcopy /E /I /Y img dist\img >nul
    echo [OK] img folder copied
)

REM Copy note folder (便利贴底图)
if exist note (
    if not exist dist\note mkdir dist\note
    xcopy /E /I /Y note dist\note >nul
    echo [OK] note folder copied
)

REM Copy changelogs
if exist changelogs (
    if not exist dist\changelogs mkdir dist\changelogs
    xcopy /E /I /Y changelogs dist\changelogs >nul
    echo [OK] changelogs copied
)

REM Copy version.json
if exist version.json (
    copy /Y version.json dist\ >nul
    echo [OK] version.json copied
)

echo.
echo ========================================
echo Build completed successfully!
echo ========================================
echo.
echo Output files:
echo   Main program: dist\xiyunlou.exe
echo   Updater:      dist\updater_new.exe
echo   Resources:    dist\img\
echo   Version:      dist\version.json
echo.
echo Next step:
echo   python build_zip.pyw   ^(生成发布 zip^)
echo.
pause