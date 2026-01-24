FROM python:3.9-slim

# Evita archivos temporales de Python y buffer en logs
ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1

WORKDIR /app

# Instalar dependencias
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copiar el código fuente
COPY . .

# Comando de inicio compatible con Render (Toma el puerto dinámico)
CMD sh -c "uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000}"
