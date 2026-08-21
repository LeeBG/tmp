@echo off
chcp 65001 > nul
cd /d "%~dp0"
title 룬 헌터 실행기

if not exist ".venv\Scripts\python.exe" (
    echo [1/2] 파이썬 가상환경을 만듭니다...
    py -3 -m venv .venv || python -m venv .venv
    if errorlevel 1 (
        echo 파이썬 3.10 이상이 설치되어 있는지 확인하세요. https://www.python.org/downloads/
        pause
        exit /b 1
    )
    echo [2/2] 필요한 모듈을 설치합니다 (PySide6, OpenCV, numpy, mss)...
    ".venv\Scripts\python.exe" -m pip install --upgrade pip
    ".venv\Scripts\python.exe" -m pip install -e .
    if errorlevel 1 (
        echo 모듈 설치에 실패했습니다. 인터넷 연결을 확인하세요.
        pause
        exit /b 1
    )
)

echo 룬 헌터를 실행합니다. 관리자 권한 창이 뜨면 [예] 를 눌러주세요.
".venv\Scripts\python.exe" -m rune_hunter %*
if errorlevel 1 pause
