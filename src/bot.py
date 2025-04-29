import os
import logging
import asyncio
import signal
from typing import Final
from pathlib import Path
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, CallbackQueryHandler, filters

# Import our modules
from db_manager import (
    init_db, is_user_authorized, is_super_admin, add_authorized_user, 
    log_unauthorized_attempt, get_unauthorized_events
)
from downloader import download_video, ensure_directories

# Enable logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", 
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()

# Define directories from environment variables
DOWNLOAD_DIR = Path(os.getenv('DOWNLOAD_DIR')).expanduser().resolve()
SAVED_VIDEOS_DIR = Path(os.getenv('SAVED_VIDEOS_DIR')).expanduser().resolve()

# Get bot token
TOKEN: Final = os.getenv('BOT_TOKEN')
if not TOKEN:
    raise ValueError("No token provided. Set BOT_TOKEN in .env file")

# Ensure directories exist and have correct permissions
if not ensure_directories(DOWNLOAD_DIR, SAVED_VIDEOS_DIR):
    raise ValueError(
        f"Error: No se puede acceder a los directorios de descarga.\n"
        f"Por favor, verifica que las rutas en .env sean correctas y tengan permisos:\n"
        f"DOWNLOAD_DIR={DOWNLOAD_DIR}\n"
        f"SAVED_VIDEOS_DIR={SAVED_VIDEOS_DIR}"
    )

async def handle_unauthorized_user(update: Update, command: str = None):
    """Handle unauthorized access attempts."""
    chat_id = update.effective_chat.id
    username = update.effective_user.username if update.effective_user else None
    
    # Log the unauthorized attempt
    await log_unauthorized_attempt(
        chat_id=chat_id,
        username=username,
        command=command or update.message.text if update.message else "unknown"
    )
    
    # Send the unauthorized message
    await update.message.reply_text("keep trying script kiddie 😎")
    logger.warning(f"Unauthorized access attempt from chat_id: {chat_id}")

async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Admin command to add authorized users. Only super admins can use this."""
    if not await is_super_admin(update.effective_chat.id):
        await handle_unauthorized_user(update, "/admin")
        return
    
    if not context.args:
        await update.message.reply_text(
            "Uso: /admin <chat_id> [username] [is_super_admin]\n"
            "is_super_admin puede ser 'true' o 'false'"
        )
        return
    
    try:
        chat_id = int(context.args[0])
        username = context.args[1] if len(context.args) > 1 else None
        is_super = (
            context.args[2].lower() == 'true'
            if len(context.args) > 2
            else False
        )
        
        await add_authorized_user(chat_id, username, is_super)
        role = "super administrador" if is_super else "usuario autorizado"
        await update.message.reply_text(
            f"Usuario {chat_id} agregado exitosamente como {role}."
        )
    except ValueError:
        await update.message.reply_text("Error: El chat_id debe ser un número.")

async def events_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Command to view unauthorized access attempts. Only super admins can use this."""
    if not await is_super_admin(update.effective_chat.id):
        await handle_unauthorized_user(update, "/events")
        return
    
    events = await get_unauthorized_events(10)  # Get last 10 events
    if not events:
        await update.message.reply_text("No hay intentos no autorizados registrados.")
        return
    
    message = "Últimos intentos no autorizados:\n\n"
    for event in events:
        chat_id, username, command, timestamp = event
        message += f"🚫 Chat ID: {chat_id}\n"
        message += f"👤 Username: {username or 'N/A'}\n"
        message += f"🔍 Comando: {command}\n"
        message += f"⏰ Fecha: {timestamp}\n"
        message += "------------------------\n"
    
    await update.message.reply_text(message)

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send a message when the command /start is issued."""
    if not await is_user_authorized(update.effective_chat.id):
        await handle_unauthorized_user(update, "/start")
        return

    await update.message.reply_text(
        "¡Hola! Envíame un enlace de video de Instagram, Facebook, TikTok o YouTube "
        "y te preguntaré qué quieres hacer con él. 🎥"
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send a message when the command /help is issued."""
    if not await is_user_authorized(update.effective_chat.id):
        await handle_unauthorized_user(update, "/help")
        return

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

async def handle_url(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle incoming URLs and show action options."""
    if not await is_user_authorized(update.effective_chat.id):
        await handle_unauthorized_user(update)
        return

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
    if not await is_user_authorized(update.callback_query.message.chat_id):
        await update.callback_query.answer("No estás autorizado para usar este bot.")
        await update.callback_query.message.delete()
        return

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
        success, status_msg, video_path = await download_video(url, output_dir)
        
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

async def shutdown(application: Application) -> None:
    """Shutdown the bot gracefully."""
    logger.info("Shutting down...")
    try:
        if application.running:
            await application.updater.stop()
            await application.stop()
            await application.shutdown()
    except Exception as e:
        logger.error(f"Error during shutdown: {e}")

async def main() -> None:
    """Start the bot."""
    if not TOKEN:
        logger.error("No bot token provided!")
        return

    # Initialize the database
    await init_db()
        
    # Initialize Application
    application = Application.builder().token(TOKEN).build()

    # Add handlers
    application.add_handler(CommandHandler("admin", admin_command))
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("events", events_command))
    application.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND & filters.Entity("url"),
            handle_url
        )
    )
    application.add_handler(CallbackQueryHandler(button_callback))

    try:
        # Start the bot
        logger.info("Starting bot...")
        await application.initialize()
        await application.start()
        
        stop_signal = asyncio.Future()
        
        def signal_handler():
            """Handle stop signals."""
            logger.info("Stop signal received")
            if not stop_signal.done():
                stop_signal.set_result(None)

        # Set up signal handlers
        for sig in (signal.SIGINT, signal.SIGTERM):
            asyncio.get_running_loop().add_signal_handler(sig, signal_handler)
        
        # Start polling in background
        application.create_task(application.updater.start_polling(drop_pending_updates=True))
        
        # Wait for stop signal
        try:
            await stop_signal
        finally:
            # Remove signal handlers and shutdown
            for sig in (signal.SIGINT, signal.SIGTERM):
                asyncio.get_running_loop().remove_signal_handler(sig)
            await shutdown(application)
            
    except Exception as e:
        logger.error(f"Error running bot: {e}")
        await shutdown(application)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
    except Exception as e:
        logger.error(f"Fatal error: {e}")