import os
import logging
import asyncio
import subprocess
from typing import Final
from pathlib import Path
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, CallbackQueryHandler, filters

# Enable logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()
TOKEN: Final = os.getenv('BOT_TOKEN')

# Create downloads directory if it doesn't exist
DOWNLOAD_DIR = Path(__file__).parent / "downloads"
DOWNLOAD_DIR.mkdir(exist_ok=True)

# Create a directory for saved videos
SAVED_VIDEOS_DIR = Path(__file__).parent / "saved_videos"
SAVED_VIDEOS_DIR.mkdir(exist_ok=True)

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send a message when the command /start is issued."""
    await update.message.reply_text(
        "¡Hola! Envíame un enlace de video de Instagram, Facebook, TikTok o YouTube "
        "y te preguntaré qué quieres hacer con él. 🎥"
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send a message when the command /help is issued."""
    await update.message.reply_text(
        "Simplemente envía un enlace de video y te daré tres opciones:\n\n"
        "1. Descargar y enviar: El video se descargará y te lo enviaré en el chat\n"
        "2. Descargar y guardar: El video se descargará y se guardará en el servidor\n"
        "3. Descargar, guardar y reenviar: El video se guardará y además te lo enviaré\n\n"
        "Plataformas soportadas:\n"
        "- Instagram (posts y reels)\n"
        "- Facebook (videos)\n"
        "- TikTok (videos)\n"
        "- YouTube (videos)"
    )

async def run_yt_dlp(url: str, output_dir: Path) -> tuple[bool, str, Path]:
    """Run yt-dlp command directly and return the downloaded file path."""
    try:
        # Prepare the command
        cmd = [
            'yt-dlp',
            '--no-warnings',
            '-f', 'best',
            '-o', str(output_dir / '%(title)s.%(ext)s'),
            url
        ]
        
        # Run the command
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        
        stdout, stderr = await process.communicate()
        
        if process.returncode != 0:
            return False, f"Error: {stderr.decode()}", Path()
            
        # Find the downloaded file
        files = list(output_dir.glob("*"))
        if not files:
            return False, "No se encontró el archivo descargado", Path()
            
        # Get the most recently modified file
        latest_file = max(files, key=lambda x: x.stat().st_mtime)
        return True, "Descarga exitosa", latest_file
        
    except Exception as e:
        return False, f"Error: {str(e)}", Path()

async def handle_url(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle incoming URLs and show action options."""
    url = update.message.text
    
    # Store URL in user_data for later use
    context.user_data['current_url'] = url
    
    # Create inline keyboard with three options
    keyboard = [
        [
            InlineKeyboardButton("📤 Descargar y enviar", callback_data="send"),
            InlineKeyboardButton("💾 Descargar y guardar", callback_data="save")
        ],
        [
            InlineKeyboardButton("📤💾 Descargar, guardar y reenviar", callback_data="save_and_send")
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        "¿Qué quieres hacer con este video?",
        reply_markup=reply_markup
    )

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle button callbacks."""
    query = update.callback_query
    await query.answer()
    
    url = context.user_data.get('current_url')
    if not url:
        await query.edit_message_text("❌ Lo siento, hubo un error. Por favor, envía el enlace nuevamente.")
        return
    
    message = await query.edit_message_text("⏳ Procesando el enlace...")
    
    try:
        # Choose directory based on action
        output_dir = SAVED_VIDEOS_DIR if query.data in ["save", "save_and_send"] else DOWNLOAD_DIR
        
        await message.edit_text("⬇️ Descargando video...")
        success, status_msg, video_path = await run_yt_dlp(url, output_dir)
        
        if not success:
            raise Exception(status_msg)
        
        if query.data == "send":
            # Solo enviar
            await message.edit_text("📤 Enviando video...")
            await context.bot.send_video(
                chat_id=query.message.chat_id,
                video=video_path,
                caption=f"📹 Video descargado"
            )
            # Clean up
            video_path.unlink()
            await message.delete()
        elif query.data == "save":
            # Solo guardar
            await message.edit_text(
                f"✅ Video guardado exitosamente como:\n"
                f"`{video_path.name}`"
            )
        else:  # save_and_send
            # Guardar y enviar
            await message.edit_text("📤 Enviando video...")
            await context.bot.send_video(
                chat_id=query.message.chat_id,
                video=video_path,
                caption=f"📹 Video guardado como:\n`{video_path.name}`"
            )
            await message.edit_text(
                f"✅ Video guardado y enviado exitosamente como:\n"
                f"`{video_path.name}`"
            )
            
    except Exception as e:
        logger.error(f"Error processing video: {e}")
        await message.edit_text(
            "❌ Lo siento, ocurrió un error al procesar el video. "
            "Por favor, verifica que el enlace sea válido."
        )

def main() -> None:
    """Start the bot."""
    if not TOKEN:
        logger.error("No bot token provided!")
        return

    application = Application.builder().token(TOKEN).build()

    # Command handlers
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("help", help_command))

    # URL handler
    application.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND & filters.Entity("url"),
            handle_url
        )
    )
    
    # Callback query handler
    application.add_handler(CallbackQueryHandler(button_callback))

    # Start the bot
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()