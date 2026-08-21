@echo off
chcp 65001 > nul
setlocal
cd /d "%~dp0"
title 룬 헌터

rem --- 관리자 권한 확인: 승격이 필요하면 이 배치 파일 자체를 다시 실행한다 -------
rem     (예전에는 파이썬이 스스로 승격해서 콘솔이 즉시 닫혔고, 오류가 보이지 않았다)
net session >nul 2>&1
if errorlevel 1 (
    echo 관리자 권한이 필요합니다. UAC 창에서 [예] 를 눌러주세요.
    echo 게임이 관리자 권한으로 실행 중이면 매크로도 같은 권한이어야 키 입력이 전달됩니다.
    powershell -NoProfile -Command "Start-Process -Verb RunAs -FilePath '%~f0' -WorkingDirectory '%~dp0'"
    exit /b 0
)

set "PY=.venv\Scripts\python.exe"

if not exist "%PY%" (
    echo [1/2] 파이썬 가상환경을 만듭니다...
    py -3 -m venv .venv 2>nul || python -m venv .venv
    if not exist "%PY%" (
        echo.
        echo 가상환경을 만들지 못했습니다. 파이썬 3.10 이상 64비트를 설치하세요.
        echo   https://www.python.org/downloads/    설치 시 "Add python.exe to PATH" 체크
        goto :end
    )
)

rem --- 매 실행마다 모듈을 확인한다 (설치가 중간에 실패한 채로 남아 있을 수 있다) ---
"%PY%" -c "import PySide6, cv2, numpy, mss, rune_hunter" >nul 2>&1
if errorlevel 1 (
    echo [2/2] 필요한 모듈을 설치합니다. 처음에는 2~3분 걸립니다...
    "%PY%" -m pip install --upgrade pip
    "%PY%" -m pip install -e .
    "%PY%" -c "import PySide6, cv2, numpy, mss, rune_hunter" >nul 2>&1
    if errorlevel 1 (
        echo.
        echo 모듈 설치에 실패했습니다. 아래 점검 결과를 확인하세요.
        echo.
        "%PY%" -m rune_hunter --diagnose
        goto :end
    )
)

echo.
echo 룬 헌터를 실행합니다. 이 창을 닫으면 프로그램도 함께 종료됩니다.
echo.
"%PY%" -m rune_hunter --no-admin %*
echo.
echo 프로그램이 종료되었습니다.
echo 오류로 닫혔다면 logs\crash.log 를 확인하거나 아래 명령으로 점검하세요.
echo   .venv\Scripts\python -m rune_hunter --diagnose

:end
echo.
pause
endlocal
