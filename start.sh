#!/bin/bash

# Crear directorios si no existen
mkdir -p data/{downloads,saved_videos,db}

# Iniciar el contenedor
docker-compose up --build -d

# Mostrar los logs
docker-compose logs -f