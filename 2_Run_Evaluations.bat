@echo off
setlocal enabledelayedexpansion

echo ============================================================
echo   Interview Evaluation Pipeline
echo ============================================================
echo.

REM --- Verify setup has been run ---
if not exist ".venv\Scripts\activate.bat" (
    echo   ERROR: Setup has not been completed yet.
    echo   Please double-click "1_Setup_For_HR.bat" first.
    echo.
    pause
    exit /b 1
)

REM --- Add local bin/ to PATH for ffmpeg ---
set "PATH=%~dp0bin;%PATH%"

REM --- Activate virtual environment ---
call .venv\Scripts\activate.bat

REM --- Load .env file into the environment ---
if exist ".env" (
    for /f "usebackq tokens=1,* delims==" %%a in (".env") do (
        set "LINE=%%a"
        REM Skip blank lines and comments
        if defined LINE (
            if not "!LINE:~0,1!"=="#" (
                set "%%a=%%b"
            )
        )
    )
) else (
    echo   ERROR: No .env file found. Please run "1_Setup_For_HR.bat" first.
    echo.
    pause
    exit /b 1
)

REM --- Verify API key is set ---
if "%ANTHROPIC_API_KEY%"=="" (
    echo   ERROR: ANTHROPIC_API_KEY is not set in your .env file.
    echo   Please open the .env file and paste your API key.
    echo.
    pause
    exit /b 1
)
if "%ANTHROPIC_API_KEY%"=="your-api-key-here" (
    echo   ERROR: You still have the placeholder API key in your .env file.
    echo   Please open the .env file and replace "your-api-key-here"
    echo   with the real API key you were given.
    echo.
    echo   Opening .env file for you now...
    start notepad "%~dp0.env"
    echo.
    pause
    exit /b 1
)

REM --- Set up folder paths ---
set "INPUT_DIR=%USERPROFILE%\Desktop\Interviews_To_Grade"
set "OUTPUT_DIR=%USERPROFILE%\Desktop\Results"

REM --- Ensure folders exist ---
if not exist "%INPUT_DIR%" mkdir "%INPUT_DIR%"
if not exist "%OUTPUT_DIR%" mkdir "%OUTPUT_DIR%"

REM --- Count files to process ---
set "FILE_COUNT=0"
for %%f in ("%INPUT_DIR%\*.mp4") do set /a FILE_COUNT+=1

if %FILE_COUNT% equ 0 (
    echo   No .mp4 files found in your "Interviews_To_Grade" folder.
    echo.
    echo   To grade interviews:
    echo     1. Place .mp4 video files into:
    echo        %INPUT_DIR%
    echo     2. Double-click this script again
    echo.
    echo   Files must be named like:
    echo     firstname-lastname-SME.mp4
    echo     firstname-lastname-QA.mp4
    echo.
    pause
    exit /b 0
)

echo   Found %FILE_COUNT% video(s) in Interviews_To_Grade.
echo.
echo   *** NOTE: If this is your first time running evaluations, ***
echo   *** downloading transcription models may take a few       ***
echo   *** minutes. The window may appear frozen -- this is      ***
echo   *** normal. Please be patient!                            ***
echo.
echo   Looking for interview videos in your Desktop
echo   "Interviews_To_Grade" folder...
echo.
echo   Starting evaluations...
echo   ------------------------------------------------------------
echo.

interview-eval --input-dir "%INPUT_DIR%" --output-dir "%OUTPUT_DIR%"

echo.
if errorlevel 1 (
    echo   ------------------------------------------------------------
    echo   There was an error during processing.
    echo   Please contact your administrator if the problem persists.
) else (
    echo   ------------------------------------------------------------
    echo   Evaluations complete!
    echo.
    echo   Results have been saved to your Desktop "Results" folder.
    echo   You can find:
    echo     - Individual reports for each candidate
    echo     - A summary CSV file with all scores
)

echo.
pause
