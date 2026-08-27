@echo off
setlocal
set "QP_HOME=%~dp0"
set "PY=%QP_HOME%.venv\Scripts\python.exe"
rem Make the package importable no matter where the user runs this from:
rem `python -m` only puts the CURRENT directory on sys.path, not this script's.
set "PYTHONPATH=%QP_HOME%;%PYTHONPATH%"
if not exist "%PY%" (
  echo [qp] venv not found: %PY%
  echo [qp] run: python -m venv .venv ^&^& .venv\Scripts\python.exe -m pip install -r requirements.txt
  exit /b 1
)
if "%~1"=="" goto :help
if /i "%~1"=="analyze" goto :pass
if /i "%~1"=="reports" goto :pass
if /i "%~1"=="cache"   goto :pass
if /i "%~1"=="test"    goto :test
if /i "%~1"=="-h"      goto :help
if /i "%~1"=="--help"  goto :help
rem bare ticker -> default to analyze
"%PY%" -m quatompitch.cli analyze %*
exit /b %errorlevel%
:pass
"%PY%" -m quatompitch.cli %*
exit /b %errorlevel%
:test
"%PY%" -m pytest "%QP_HOME%tests" -q
exit /b %errorlevel%
:help
"%PY%" -m quatompitch.cli --help
exit /b %errorlevel%
