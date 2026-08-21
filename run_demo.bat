@echo off
chcp 65001 > nul
setlocal
cd /d "%~dp0"
title 룬 헌터 데모 (게임 없이 동작 확인)

rem 데모 모드는 실제 키를 보내지 않으므로 관리자 권한이 필요 없다.
set "PY=.venv\Scripts\python.exe"

if not exist "%PY%" (
    echo 가상환경이 없습니다. 먼저 run.bat 을 한 번 실행해 설치를 완료하세요.
    goto :end
)

"%PY%" -c "import PySide6, cv2, numpy, mss, rune_hunter" >nul 2>&1
if errorlevel 1 (
    echo 모듈이 설치되지 않았습니다. 설치를 시도합니다...
    "%PY%" -m pip install -e .
)

echo 데모 모드로 실행합니다. (실제 키 입력 없음)
echo.
"%PY%" -m rune_hunter --demo --no-admin
echo.
echo 프로그램이 종료되었습니다. 오류가 있었다면 logs\crash.log 를 확인하세요.

:end
echo.
pause
endlocal
