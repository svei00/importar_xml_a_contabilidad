@echo off
echo Iniciando Procesador SAT a ContpaqI...

REM Revisar si Python esta instalado
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo Error: Python no esta instalado o no esta en el PATH.
    pause
    exit /b
)

REM Crear entorno virtual si no existe
if not exist "venv\" (
    echo Creando entorno virtual...
    python -m venv venv
)

REM Activar e instalar requerimientos
call venv\Scripts\activate
echo Instalando/Actualizando librerias...
pip install pandas scikit-learn requests openpyxl >nul 2>&1

echo Ejecutando la aplicacion...
python main.py

pause