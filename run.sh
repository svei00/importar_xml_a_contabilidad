#!/bin/bash
echo "Iniciando Procesador SAT a ContpaqI..."

# Revisar si Python3 esta instalado
if ! command -v python3 &> /dev/null
then
    echo "Error: Python3 no esta instalado."
    exit
fi

# Crear entorno virtual si no existe
if [ ! -d "venv" ]; then
    echo "Creando entorno virtual..."
    python3 -m venv venv
fi

# Activar e instalar requerimientos
source venv/bin/activate
echo "Instalando/Actualizando librerias..."
pip install pandas scikit-learn requests openpyxl > /dev/null 2>&1

echo "Ejecutando la aplicacion..."
python3 main.py