@echo off
title Procesador Contable ML

echo ===============================
echo INICIANDO SISTEMA CONTABLE ML
echo ===============================

REM Activar entorno virtual si tienes uno (opcional)
REM call venv\Scripts\activate

echo.
echo Ejecutando Python...
python main.py

echo.
echo ===============================
echo PROCESO TERMINADO
echo Revisa el archivo salida.xlsx
echo ===============================

pause