@echo off
REM Schedule via Windows Task Scheduler at 3:00 PM IST (9:30 AM UTC)
REM Task name: MeetingPrepPipeline
cd /d D:\personal-claude-automations\meeting_notes_preperations
.venv\Scripts\python.exe -m src
