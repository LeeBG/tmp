@echo off
chcp 65001 > nul
cd /d "%~dp0"
title 룬 헌터 데모 (게임 없이 동작 확인)

if not exist ".venv\Scripts\python.exe" (
    echo 먼저 run.bat 을 한 번 실행해 설치를 완료하세요.
    pause
    exit /b 1
)

rem 데모 모드는 실제 키를 보내지 않으므로 관리자 권한이 필요 없다.
".venv\Scripts\python.exe" -m rune_hunter --demo --no-admin
if errorlevel 1 pause
