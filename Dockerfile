FROM python:3.9-slim

# Configuración Python
ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1

# Directorio de trabajo dentro del contenedor
WORKDIR /code

# Copiamos los archivos de la carpeta 'app' hacia el contenedor
COPY app/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ .

# Comando de arranque para Render
CMD sh -c "uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000}"
