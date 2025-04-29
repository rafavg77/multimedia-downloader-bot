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

2. Crea un entorno virtual e instala las dependencias:
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
     DOWNLOAD_DIR=src/downloads      # Directorio para descargas temporales
     SAVED_VIDEOS_DIR=src/saved_videos  # Directorio para videos guardados
     SUPER_ADMIN_CHAT_ID=
     ```

## Uso

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

## Contribuir

1. Haz un fork del repositorio
2. Crea una rama para tu característica (`git checkout -b feature/AmazingFeature`)
3. Haz commit de tus cambios (`git commit -m 'Add some AmazingFeature'`)
4. Push a la rama (`git push origin feature/AmazingFeature`)
5. Abre un Pull Request

## Licencia

Este proyecto está licenciado bajo la Licencia MIT - ver el archivo [LICENSE](LICENSE) para más detalles.

## Contacto

Tu Nombre - [@tutwitter](https://twitter.com/tutwitter)

Link del proyecto: [https://github.com/yourusername/multimedia-downloader-bot](https://github.com/yourusername/multimedia-downloader-bot)