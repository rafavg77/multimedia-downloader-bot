FROM python:3.11-slim-bookworm

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Instalar dependencias del sistema
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Crear usuario y grupo con IDs dinámicos
ARG PUID=1000
ARG PGID=1000
ENV PUID=${PUID}
ENV PGID=${PGID}

# Crear usuario no root con IDs dinámicos
RUN groupmod -o -g ${PGID} www-data && \
    usermod -o -u ${PUID} www-data && \
    mkdir -p /data/downloads /data/saved_videos /data/db && \
    chown -R www-data:www-data /data && \
    chown -R www-data:www-data /app

# Copiar requirements.txt primero para aprovechar la caché de Docker
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copiar el código fuente con permisos del usuario de ejecución
COPY --chown=www-data:www-data src/ ./src/

# Cambiar al usuario www-data
USER www-data

EXPOSE 9099

CMD ["python", "src/bot.py"]