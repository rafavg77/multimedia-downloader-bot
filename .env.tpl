# ==============================================================================
# Multimedia Downloader Bot - Environment Template (1Password)
# Vault: HomeLab
# Item:  MultimediaBot
# ==============================================================================

# Telegram Bot
BOT_TOKEN=op://HomeLab/MultimediaBot/BOT_TOKEN
SUPER_ADMIN_CHAT_ID=op://HomeLab/MultimediaBot/SUPER_ADMIN_CHAT_ID
STARTUP_NOTIFY_CHAT_ID=op://HomeLab/MultimediaBot/STARTUP_NOTIFY_CHAT_ID
SEND_STARTUP_NOTIFICATION=op://HomeLab/MultimediaBot/SEND_STARTUP_NOTIFICATION

# Base de datos PostgreSQL
POSTGRES_DB=op://HomeLab/MultimediaBot/POSTGRES_DB
POSTGRES_USER=op://HomeLab/MultimediaBot/POSTGRES_USER
POSTGRES_PASSWORD=op://HomeLab/MultimediaBot/POSTGRES_PASSWORD

# Almacenamiento NFS (Kyubi)
NFS_SERVER=op://HomeLab/MultimediaBot/NFS_SERVER
NFS_EXPORT_DOWNLOADS=op://HomeLab/MultimediaBot/NFS_EXPORT_DOWNLOADS
NFS_EXPORT_SAVED_VIDEOS=op://HomeLab/MultimediaBot/NFS_EXPORT_SAVED_VIDEOS
NFS_VERS=op://HomeLab/MultimediaBot/NFS_VERS
NFS_MOUNT_BASE=op://HomeLab/MultimediaBot/NFS_MOUNT_BASE

# Configuración del Sistema
PUID=op://HomeLab/MultimediaBot/PUID
PGID=op://HomeLab/MultimediaBot/PGID
TZ=op://HomeLab/MultimediaBot/TZ

# Rutas internas en el contenedor (no modificar)
DOWNLOAD_DIR=/data/downloads
SAVED_VIDEOS_DIR=/data/saved_videos

# Observabilidad & Telemetría Prometheus
METRICS_PORT=9099

