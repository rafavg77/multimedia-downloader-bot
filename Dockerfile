FROM python:3.11-slim

WORKDIR /app

# Instalar dependencias del sistema
RUN apt-get update && apt-get install -y \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Crear usuario no root
RUN useradd -m -u 1000 botuser && \
    mkdir -p /data/downloads /data/saved_videos /data/db && \
    chown -R botuser:botuser /data && \
    chown -R botuser:botuser /app

# Copiar requirements.txt primero para aprovechar la caché de Docker
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copiar el código fuente
COPY src/ ./src/

# Cambiar al usuario no root
USER botuser

CMD ["python", "src/bot.py"]