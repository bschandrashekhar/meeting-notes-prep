@echo off
REM ============================================================
REM  Schedule Meeting Prep to run daily at 7 PM
REM  Run this script as Administrator to create the scheduled task.
REM ============================================================

SET TASK_NAME=MeetingPrepAutomation
SET PROJECT_DIR=%~dp0
SET PYTHON_EXE=python
SET LOG_FILE=%PROJECT_DIR%logs\scheduled_run.log

echo Creating scheduled task: %TASK_NAME%
echo Project directory: %PROJECT_DIR%
echo.

REM Delete existing task if it exists
schtasks /Delete /TN "%TASK_NAME%" /F >nul 2>&1

REM Create the scheduled task
REM /SC DAILY  = run every day
REM /ST 19:00  = at 7:00 PM
REM /TR        = the command to run
schtasks /Create ^
    /TN "%TASK_NAME%" ^
    /SC DAILY ^
    /ST 19:00 ^
    /TR "cmd /c cd /d \"%PROJECT_DIR%\" && %PYTHON_EXE% -m src.main >> \"%LOG_FILE%\" 2>&1" ^
    /RL HIGHEST ^
    /F

IF %ERRORLEVEL% EQU 0 (
    echo.
    echo SUCCESS: Scheduled task created!
    echo   Task name: %TASK_NAME%
    echo   Schedule:  Daily at 7:00 PM
    echo   Log file:  %LOG_FILE%
    echo.
    echo To verify:  schtasks /Query /TN "%TASK_NAME%"
    echo To run now: schtasks /Run /TN "%TASK_NAME%"
    echo To delete:  schtasks /Delete /TN "%TASK_NAME%" /F
) ELSE (
    echo.
    echo FAILED: Could not create scheduled task.
    echo Make sure you are running this script as Administrator.
)

pause
