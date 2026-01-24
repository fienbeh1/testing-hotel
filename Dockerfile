FROM python:3.9-slim

# Evita archivos basura
ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1

# === ZONA HORARIA SALTILLO/MÉXICO ===
# Instalamos la base de datos de zonas horarias y configuramos
RUN apt-get update && apt-get install -y tzdata
ENV TZ="America/Monterrey"
# ====================================

WORKDIR /code

# Instalar dependencias
COPY app/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copiar App
COPY app/ .

# Arrancar
CMD sh -c "uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000}"
