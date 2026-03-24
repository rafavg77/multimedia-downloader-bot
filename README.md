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

   # Opcionales (recomendado para producción)
   LOG_LEVEL=INFO
   # Límite “seguro” para evitar 413 al enviar a Telegram
   TELEGRAM_MAX_UPLOAD_MB=45

   # Transcodificación para compatibilidad con Telegram
   # (evita el caso “primer frame estático + audio” con algunos codecs)
   TRANSCODE_FOR_TELEGRAM=1
   FFMPEG_CRF=23
   FFMPEG_PRESET=veryfast
     ```

Notas:
- Si tu token llegó a aparecer en logs alguna vez, regénéralo en BotFather.
- `TRANSCODE_FOR_TELEGRAM=1` convierte a MP4 H.264/AAC antes de enviar a Telegram.

## Uso

### Opción A: Docker Compose (Docker Hub / producción)

Este modo usa `docker-compose.yml` y descarga la imagen desde Docker Hub. También incluye un contenedor `mediabot-init` que crea y ajusta permisos de los volúmenes automáticamente (no necesitas crear carpetas manualmente).

```bash
docker compose up -d
docker compose logs -f mediabot
```

### 📺 Guardar descargas en Raspberry Pi (DLNA)

Si no quieres que la opción “Descargar y enviar” use el disco del contenedor/host y prefieres que los archivos se guarden en tu Raspberry Pi (carpeta del servidor DLNA), lo ideal es montar una carpeta remota (NFS o SMB) y mapearla a `/data/downloads`.

Hay 2 formas comunes:

#### Opción 1: Montar en el host (recomendado)

1) Monta la carpeta DLNA del Raspberry en el host donde corre Docker, por ejemplo a `/mnt/dlna`.

2) Cambia el bind-mount de downloads en tu compose para apuntar a ese mount:

```yaml
services:
   mediabot:
      volumes:
         - /mnt/dlna:/data/downloads
```

De esta forma, todo lo que caiga en `/data/downloads` se guarda físicamente en el Raspberry.

#### Opción 2: Volumen Docker con NFS

Ejemplo (ajusta `PI_IP` y `EXPORT_PATH`):

```yaml
volumes:
   dlna_downloads:
      driver: local
      driver_opts:
         type: nfs
         o: addr=PI_IP,rw,nolock,soft
         device: ":/EXPORT_PATH"

services:
   mediabot:
      volumes:
         - dlna_downloads:/data/downloads
```

Importante:
- DLNA normalmente requiere que los videos queden dentro de la carpeta que el servidor DLNA indexa (por ejemplo `/srv/dlna/videos`). Esa es la ruta que debes exportar/montar.
- Si usas NFS/SMB, asegúrate de que los permisos permitan escritura por `PUID/PGID`.

##### ✅ Ejemplo NFS con tu Raspberry

Tu DLNA indexa la carpeta:
- `/home/tota77/Videos` (según `media_dir=V,/home/tota77/Videos`)

Este repo incluye un override listo para NFS:
- [docker-compose.nfs.yml](docker-compose.nfs.yml)

Variables usadas por el override:
- `NFS_SERVER` (obligatoria): IP/host del servidor NFS
- `NFS_EXPORT_DOWNLOADS` (obligatoria): ruta exportada para `/data/downloads`
- `NFS_EXPORT_SAVED_VIDEOS` (obligatoria): ruta exportada para `/data/saved_videos`
- `NFS_VERS` (opcional): versión NFS, default `4`

1) En el Raspberry, crea las carpetas destino (deben existir para poder montar por NFS):

```bash
mkdir -p /home/tota77/Videos/mediabot/downloads
mkdir -p /home/tota77/Videos/mediabot/saved_videos
```

2) En el Raspberry, exporta la ruta por NFS (ejemplo básico en `/etc/exports`). Ajusta la red/IP a tu caso:

```text
/home/tota77/Videos 192.168.68.0/24(rw,sync,no_subtree_check)
```

Luego aplica los exports:

```bash
sudo exportfs -ra
```

3) En el host donde corre Docker, asegúrate de tener soporte de NFS (en Debian/Ubuntu suele ser `nfs-common`).

4) Levanta el stack usando el override:

```bash
docker compose -f docker-compose.yml -f docker-compose.nfs.yml up -d
docker compose logs -f mediabot
```

##### ✅ Si ya montaste el NFS en el host (bind-mount)

Si el NFS ya está montado en tu servidor (por ejemplo en `/mnt/raspi_videos`), usa el override de bind-mount:
- [docker-compose.nfs.bind.yml](docker-compose.nfs.bind.yml)

1) Verifica que el mount existe:

```bash
mount | grep -i nfs
df -h | grep -i nfs
```

2) Exporta la variable `NFS_MOUNT_BASE` (o ponla en tu `.env`):

```bash
export NFS_MOUNT_BASE=/mnt/raspi_videos
```

3) Levanta el stack:

```bash
docker compose -f docker-compose.yml -f docker-compose.nfs.bind.yml up -d
docker compose logs -f mediabot
```

#### Producción (con archivo `.env`)

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