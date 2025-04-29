#!/bin/bash

# Detectar el directorio del script
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"

# Verificar que se ejecuta como root
if [ "$EUID" -ne 0 ]; then 
    echo "Este script debe ejecutarse como root (sudo)"
    exit 1
fi

# Crear el usuario del servicio si no existe
if ! id "mediabot" &>/dev/null; then
    useradd -r -s /bin/false mediabot
fi

# Crear directorios de trabajo
mkdir -p /opt/mediabot
cp -r "$SCRIPT_DIR"/* /opt/mediabot/

# Asegurarse de que el entorno virtual existe
python3 -m venv /opt/mediabot/venv

# Instalar dependencias
/opt/mediabot/venv/bin/pip install -r /opt/mediabot/requirements.txt

# Crear directorios personalizables para videos y establecer permisos
read -p "Ingrese el directorio para descargas [/var/lib/mediabot/downloads]: " download_dir
download_dir=${download_dir:-/var/lib/mediabot/downloads}

read -p "Ingrese el directorio para videos guardados [/var/lib/mediabot/saved_videos]: " saved_dir
saved_dir=${saved_dir:-/var/lib/mediabot/saved_videos}

mkdir -p "$download_dir"
mkdir -p "$saved_dir"
chown -R mediabot:mediabot "$download_dir" "$saved_dir"
chmod -R 755 "$download_dir" "$saved_dir"

# Crear/actualizar archivo .env
cat > /opt/mediabot/.env << EOL
# Configuración del Bot
BOT_TOKEN=tu_token_aqui
SUPER_ADMIN_CHAT_ID=tu_chat_id_aqui

# Directorios personalizados
DOWNLOAD_DIR=${download_dir}
SAVED_VIDEOS_DIR=${saved_dir}
EOL

# Asegurar permisos del archivo .env
chown mediabot:mediabot /opt/mediabot/.env
chmod 600 /opt/mediabot/.env

# Crear el archivo de servicio systemd
cat > /etc/systemd/system/mediabot.service << EOL
[Unit]
Description=Telegram Media Downloader Bot
After=network.target

[Service]
Type=simple
User=mediabot
Group=mediabot
WorkingDirectory=/opt/mediabot
Environment=PYTHONPATH=/opt/mediabot
EnvironmentFile=/opt/mediabot/.env
ExecStart=/opt/mediabot/venv/bin/python src/bot.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOL

# Recargar systemd y habilitar el servicio
systemctl daemon-reload
systemctl enable mediabot.service

echo "Instalación completada."
echo "Por favor, edita el archivo /opt/mediabot/.env y configura:"
echo "1. BOT_TOKEN con el token de tu bot"
echo "2. SUPER_ADMIN_CHAT_ID con tu chat ID de Telegram"
echo ""
echo "Comandos útiles:"
echo "- Iniciar el bot: sudo systemctl start mediabot"
echo "- Ver el estado: sudo systemctl status mediabot"
echo "- Ver los logs: sudo journalctl -u mediabot -f"