FROM python:3.9-slim

ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1
ENV TZ="America/Monterrey"

RUN apt-get update && apt-get install -y tzdata
WORKDIR /code

COPY app/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ .

# Render will pass a $PORT variable, so we use this:
CMD uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000}