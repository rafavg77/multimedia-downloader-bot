# Multimedia Downloader Bot

Bot de Telegram que permite descargar videos de diferentes plataformas sociales y gestionarlos de manera flexible.

## Características

- 📥 Descarga videos de múltiples plataformas:
  - Instagram (posts y reels)
  - Facebook (videos)
  - TikTok (videos)
  - YouTube (videos)

- 🎛 Opciones flexibles para cada video:
  - Descargar y enviar al chat
  - Descargar y guardar en el servidor
  - Descargar, guardar y reenviar al chat

## Requisitos

- Python 3.8+
- python-telegram-bot v22.0
- yt-dlp (última versión)
- python-dotenv

## Instalación

1. Clona el repositorio:
```bash
git clone https://github.com/yourusername/multimedia-downloader-bot.git
cd multimedia-downloader-bot
```

2. Crea un entorno virtual e instala las dependencias (opcional, si lo ejecutarás sin Docker):
```bash
python -m venv venv
source venv/bin/activate  # En Windows: venv\Scripts\activate
pip install -r requirements.txt
```

3. Configura las variables de entorno:
   - Crea un archivo `.env` en la raíz del proyecto
   - Configura las siguientes variables:
     ```
  BOT_TOKEN=tu_token_aquí
  SUPER_ADMIN_CHAT_ID=123456789
  PUID=1000
  PGID=1000
  TZ=America/Monterrey
     ```

## Uso

### Opción A: Docker Compose (Docker Hub / producción)

Este modo usa `docker-compose.yml` y descarga la imagen desde Docker Hub. También incluye un contenedor `mediabot-init` que crea y ajusta permisos de los volúmenes automáticamente (no necesitas crear carpetas manualmente).

```bash
docker compose up -d
docker compose logs -f mediabot
```

#### Portainer (Stack)

En Portainer, el archivo `.env` no existe automáticamente en la carpeta interna del stack (`/data/compose/...`). Por eso, para que funcione:

- Ve a tu Stack → **Environment variables**
- Agrega al menos:
   - `BOT_TOKEN`
   - `SUPER_ADMIN_CHAT_ID` (opcional si tu bot lo requiere)
   - `PUID` (default 1000)
   - `PGID` (default 1000)
   - `TZ` (ej. `America/Monterrey`)

Luego redeploy del stack.

#### Producción sin Portainer (con archivo `.env`)

Si lo ejecutas en un servidor con Docker Compose “normal” y quieres usar un archivo `.env`, usa:

```bash
docker compose --env-file .env up -d
docker compose logs -f mediabot
```

### Opción B: Docker Compose (build local)

Este modo usa `docker-compose.local.yml` y construye la imagen localmente.

```bash
docker compose -f docker-compose.local.yml up -d --build
docker compose -f docker-compose.local.yml logs -f mediabot
```

### Opción C: Ejecutar sin Docker

1. Inicia el bot:
```bash
python src/bot.py
```

2. En Telegram:
   - Inicia una conversación con tu bot
   - Envía el comando `/start` para ver el mensaje de bienvenida
   - Envía el comando `/help` para ver las instrucciones detalladas
   - Envía cualquier URL de video soportada
   - Selecciona la acción que deseas realizar con el video

## Estructura del Proyecto

```
multimedia-downloader-bot/
├── README.md
├── requirements.txt
└── src/
    ├── bot.py
    ├── downloads/      # Carpeta temporal para descargas
    └── saved_videos/   # Almacenamiento permanente de videos
```

## 📋 Ver logs del contenedor

Hay varias formas de ver los logs del contenedor:

1. Ver los logs en tiempo real:
```bash
docker logs -f mediabot
```

2. Ver los últimos N líneas de logs:
```bash
docker logs --tail 100 mediabot
```

3. Ver logs desde una fecha específica:
```bash
docker logs --since 2024-04-28T00:00:00Z mediabot
```

4. En Portainer:
   - Ve a Containers
   - Haz clic en el contenedor 'mediabot'
   - Ve a la pestaña 'Logs'
   - Puedes activar 'Auto-refresh' para ver los logs en tiempo real

Los logs mostrarán:
- Errores y excepciones
- Intentos de acceso no autorizados
- Descargas exitosas/fallidas de videos
- Información de inicio/parada del bot

## 🚀 Publicar imagen en Docker Hub

Requisitos:
- Tener una cuenta en Docker Hub
- Tener creado (o permiso sobre) el repositorio `rafavg77/multimedia-downloader-bot`

### Build y Push (latest)

```bash
docker login
docker build -t rafavg77/multimedia-downloader-bot:latest .
docker push rafavg77/multimedia-downloader-bot:latest
```

### Build y Push con versión (recomendado)

```bash
VERSION=1.0.0
docker build -t rafavg77/multimedia-downloader-bot:$VERSION -t rafavg77/multimedia-downloader-bot:latest .
docker push rafavg77/multimedia-downloader-bot:$VERSION
docker push rafavg77/multimedia-downloader-bot:latest
```

## Contribuir

1. Haz un fork del repositorio
2. Crea una rama para tu característica (`git checkout -b feature/AmazingFeature`)
3. Haz commit de tus cambios (`git commit -m 'Add some AmazingFeature'`)
4. Push a la rama (`git push origin feature/AmazingFeature`)
5. Abre un Pull Request

## Licencia

Este proyecto está licenciado bajo la Licencia MIT - ver el archivo [LICENSE](LICENSE) para más detalles.

## Contacto

rafavg77 - [@rafavg77](https://x.com/rafavg77)

Link del proyecto: [https://github.com/rafavg77/multimedia-downloader-bot](https://github.com/rafavg77/multimedia-downloader-bot)