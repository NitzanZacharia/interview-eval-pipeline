@echo off
setlocal enabledelayedexpansion

echo ============================================================
echo   Interview Evaluation Pipeline - First-Time Setup
echo ============================================================
echo.

REM --- 1. Check for Python ---
echo [Step 1/6] Checking for Python...
python --version >nul 2>&1
if errorlevel 1 (
    echo.
    echo   ERROR: Python is not installed on this computer.
    echo.
    echo   Please install Python using ONE of these options:
    echo.
    echo     Option A - Windows Store (easiest):
    echo       1. Open the Microsoft Store app
    echo       2. Search for "Python 3.12"
    echo       3. Click "Get" / "Install"
    echo.
    echo     Option B - python.org:
    echo       1. Go to https://www.python.org/downloads/
    echo       2. Download the latest version
    echo       3. Run the installer
    echo       4. IMPORTANT: Check the box that says
    echo          "Add Python to PATH" at the bottom of the installer
    echo.
    echo   After installing Python, close this window and
    echo   double-click this setup script again.
    echo.
    pause
    exit /b 1
)
for /f "tokens=*" %%v in ('python --version 2^>^&1') do echo   Found %%v
echo.

REM --- 2. Create virtual environment ---
echo [Step 2/6] Creating a local Python environment...
if exist ".venv" (
    echo   Virtual environment already exists, skipping.
) else (
    python -m venv .venv
    if errorlevel 1 (
        echo   ERROR: Failed to create virtual environment.
        echo   Please make sure Python is installed correctly.
        pause
        exit /b 1
    )
    echo   Done.
)
echo.

REM --- 3. Install dependencies ---
echo [Step 3/6] Installing project dependencies...
echo   (This may take a few minutes on the first run)
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip --quiet >nul 2>&1
pip install -e . --quiet
if errorlevel 1 (
    echo.
    echo   ERROR: Failed to install dependencies.
    echo   Please contact your administrator.
    pause
    exit /b 1
)
echo   Done.
echo.

REM --- 4. Download FFmpeg ---
echo [Step 4/6] Setting up FFmpeg (audio processing tool)...
if exist "bin\ffmpeg.exe" (
    echo   FFmpeg already downloaded, skipping.
) else (
    echo   Downloading FFmpeg... this may take a minute.

    if not exist "bin" mkdir bin

    set "FFMPEG_URL=https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip"
    set "FFMPEG_ZIP=%TEMP%\ffmpeg_download.zip"
    set "FFMPEG_EXTRACT=%TEMP%\ffmpeg_extract"

    REM Download using curl (built into Windows 10/11)
    curl -L -o "!FFMPEG_ZIP!" "!FFMPEG_URL!" --progress-bar
    if errorlevel 1 (
        echo.
        echo   ERROR: Failed to download FFmpeg.
        echo   Please check your internet connection and try again.
        pause
        exit /b 1
    )

    REM Extract using tar (built into Windows 10/11)
    if exist "!FFMPEG_EXTRACT!" rmdir /s /q "!FFMPEG_EXTRACT!"
    mkdir "!FFMPEG_EXTRACT!"
    tar -xf "!FFMPEG_ZIP!" -C "!FFMPEG_EXTRACT!" 2>nul
    if errorlevel 1 (
        echo.
        echo   ERROR: Failed to extract FFmpeg.
        pause
        exit /b 1
    )

    REM Find and copy ffmpeg.exe from the extracted folder
    set "FOUND="
    for /r "!FFMPEG_EXTRACT!" %%f in (ffmpeg.exe) do (
        if not defined FOUND (
            copy "%%f" "bin\ffmpeg.exe" >nul
            set "FOUND=1"
        )
    )

    REM Clean up temp files
    del "!FFMPEG_ZIP!" 2>nul
    rmdir /s /q "!FFMPEG_EXTRACT!" 2>nul

    if not defined FOUND (
        echo   ERROR: Could not find ffmpeg.exe in the download.
        pause
        exit /b 1
    )
    echo   Done.
)
echo.

REM --- 5. Create .env file for API key ---
echo [Step 5/6] Setting up API key configuration...
if exist ".env" (
    echo   .env file already exists, skipping.
) else (
    if exist ".env.example" (
        copy ".env.example" ".env" >nul
    ) else (
        echo ANTHROPIC_API_KEY=your-api-key-here> .env
    )
    echo   Created .env file.
)

REM Check if the key is still the placeholder
findstr /c:"your-api-key-here" ".env" >nul 2>&1
if not errorlevel 1 (
    echo.
    echo   ************************************************************
    echo   *  ACTION REQUIRED: You need to add your API key!          *
    echo   *                                                          *
    echo   *  A Notepad window will open with the .env file.          *
    echo   *  Replace "your-api-key-here" with the real API key       *
    echo   *  you were given, then save the file (Ctrl+S) and close.  *
    echo   ************************************************************
    echo.
    start notepad "%~dp0.env"
) else (
    echo   API key appears to be configured.
)
echo.

REM --- 6. Create Desktop folders ---
echo [Step 6/6] Creating Desktop folders...
set "INPUT_FOLDER=%USERPROFILE%\Desktop\Interviews_To_Grade"
set "RESULTS_FOLDER=%USERPROFILE%\Desktop\Results"

if not exist "!INPUT_FOLDER!" (
    mkdir "!INPUT_FOLDER!"
    echo   Created: Desktop\Interviews_To_Grade
) else (
    echo   Desktop\Interviews_To_Grade already exists.
)

if not exist "!RESULTS_FOLDER!" (
    mkdir "!RESULTS_FOLDER!"
    echo   Created: Desktop\Results
) else (
    echo   Desktop\Results already exists.
)
echo.

echo ============================================================
echo   Setup Complete!
echo ============================================================
echo.
echo   NEXT STEPS:
echo     1. Make sure you pasted your API key into the .env file
echo        (Notepad should be open -- save and close it)
echo     2. Place interview videos (.mp4 files) into the
echo        "Interviews_To_Grade" folder on your Desktop
echo     3. Double-click "2_Run_Evaluations.bat" to grade them
echo.
echo   Video files must be named like:
echo     firstname-lastname-SME.mp4
echo     firstname-lastname-QA.mp4
echo.
pause
