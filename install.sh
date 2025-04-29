#!/bin/bash

# Función para mostrar mensajes con formato
print_step() {
    echo -e "\n\033[1;34m[PASO]\033[0m $1..."
}

print_success() {
    echo -e "\033[1;32m[✔]\033[0m $1"
}

print_error() {
    echo -e "\033[1;31m[✘]\033[0m $1"
}

# Detectar el directorio del script
print_step "Detectando directorio del script"
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
print_success "Directorio del script: $SCRIPT_DIR"

# Verificar que se ejecuta como root
if [ "$EUID" -ne 0 ]; then 
    print_error "Este script debe ejecutarse como root (sudo)"
    exit 1
fi

# Crear el usuario del servicio si no existe
print_step "Configurando usuario del servicio"
if ! id "mediabot" &>/dev/null; then
    useradd -r -s /bin/false mediabot
    print_success "Usuario mediabot creado"
else
    print_success "Usuario mediabot ya existe"
fi

# Crear directorios de trabajo
print_step "Configurando directorios de trabajo"
mkdir -p /opt/mediabot
cp -r "$SCRIPT_DIR"/* /opt/mediabot/
print_success "Directorios de trabajo configurados en /opt/mediabot"

# Asegurarse de que el entorno virtual existe
print_step "Creando entorno virtual Python"
python3 -m venv /opt/mediabot/venv
print_success "Entorno virtual creado"

# Instalar dependencias
print_step "Instalando dependencias del proyecto"
/opt/mediabot/venv/bin/pip install -r /opt/mediabot/requirements.txt
print_success "Dependencias instaladas correctamente"

# Crear directorios personalizables y establecer permisos
print_step "Configurando directorios personalizados"
read -p "Ingrese el directorio para descargas [/var/lib/mediabot/downloads]: " download_dir
download_dir=${download_dir:-/var/lib/mediabot/downloads}

read -p "Ingrese el directorio para videos guardados [/var/lib/mediabot/saved_videos]: " saved_dir
saved_dir=${saved_dir:-/var/lib/mediabot/saved_videos}

# Crear directorio para la base de datos
data_dir="/var/lib/mediabot/data"

# Crear todos los directorios necesarios
print_step "Creando estructura de directorios"
mkdir -p "$download_dir"
mkdir -p "$saved_dir"
mkdir -p "$data_dir"
print_success "Directorios creados:\n- $download_dir\n- $saved_dir\n- $data_dir"

# Establecer permisos
print_step "Estableciendo permisos de directorios"
chown -R mediabot:mediabot "$download_dir" "$saved_dir" "$data_dir"
chmod -R 755 "$download_dir" "$saved_dir"
chmod 700 "$data_dir"
print_success "Permisos establecidos correctamente"

# Crear/actualizar archivo .env
print_step "Generando archivo de configuración"
cat > /opt/mediabot/.env << EOL
# Configuración del Bot
BOT_TOKEN=tu_token_aqui
SUPER_ADMIN_CHAT_ID=tu_chat_id_aqui

# Directorios personalizados
DOWNLOAD_DIR=${download_dir}
SAVED_VIDEOS_DIR=${saved_dir}
DB_PATH=${data_dir}/users.db
EOL

# Asegurar permisos del archivo .env
chown mediabot:mediabot /opt/mediabot/.env
chmod 600 /opt/mediabot/.env
print_success "Archivo de configuración creado en /opt/mediabot/.env"

# Crear el archivo de servicio systemd
print_step "Configurando servicio systemd"
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
print_step "Habilitando servicio systemd"
systemctl daemon-reload
systemctl enable mediabot.service
print_success "Servicio mediabot habilitado"

print_success "¡Instalación completada!"
echo -e "\n\033[1;33m[!] IMPORTANTE: Pasos siguientes\033[0m"
echo "1. Edita el archivo /opt/mediabot/.env y configura:"
echo "   - BOT_TOKEN con el token de tu bot"
echo "   - SUPER_ADMIN_CHAT_ID con tu chat ID de Telegram"
echo -e "\n\033[1;36m[i] Comandos útiles:\033[0m"
echo "- Iniciar el bot:    sudo systemctl start mediabot"
echo "- Ver el estado:     sudo systemctl status mediabot"
echo "- Ver los logs:      sudo journalctl -u mediabot -f"