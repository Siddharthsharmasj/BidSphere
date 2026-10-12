@echo off
setlocal
cd /d %~dp0
if not exist venv\Scripts\python.exe (
    py -3.14 -m venv venv || goto :error
)
call venv\Scripts\activate.bat
python -m pip install -r requirements.txt || goto :error
python manage.py migrate || goto :error
python manage.py seed_demo --reset || goto :error
python manage.py runserver
exit /b 0
:error
echo.
echo Setup failed. Copy the error above and share it for diagnosis.
pause
exit /b 1
