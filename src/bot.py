import os
import json
import socket
import logging
import asyncio
import signal
from typing import Final
from pathlib import Path
from urllib.parse import urlparse, urlunparse
from urllib.request import urlopen, Request
from telegram.error import BadRequest
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, CallbackQueryHandler, filters

# Import our modules
from db_manager import (
    init_db, is_user_authorized, is_super_admin, add_authorized_user,
    remove_authorized_user, list_authorized_users, log_unauthorized_attempt,
    get_unauthorized_events
)
from downloader import download_video, ensure_directories, transcode_to_telegram_mp4

# Load environment variables
load_dotenv()

# Define directories from environment variables with valores por defecto para Docker
DOWNLOAD_DIR = Path(os.getenv('DOWNLOAD_DIR', '/data/downloads')).resolve()
SAVED_VIDEOS_DIR = Path(os.getenv('SAVED_VIDEOS_DIR', '/data/saved_videos')).resolve()

# Get bot token
TOKEN: Final = os.getenv('BOT_TOKEN')
if not TOKEN:
    raise ValueError("No token provided. Set BOT_TOKEN environment variable")

def _sanitize_url_for_log(raw_url: str) -> str:
    """Remove query/fragment to avoid logging sensitive params."""
    try:
        parsed = urlparse(raw_url)
        return urlunparse(parsed._replace(query="", fragment=""))
    except Exception:
        return raw_url

class _RedactBotTokenFilter(logging.Filter):
    def __init__(self, token: str | None):
        super().__init__()
        self._token = token or ""

    def filter(self, record: logging.LogRecord) -> bool:
        if not self._token:
            return True
        try:
            message = record.getMessage()
        except Exception:
            return True
        if self._token in message:
            record.msg = message.replace(self._token, "<BOT_TOKEN>")
            record.args = ()
        return True

class _SuppressNoisyLibsFilter(logging.Filter):
    _prefixes = (
        "httpx",
        "httpcore",
        "telegram",
        "telegram.ext",
        "apscheduler",
    )

    def filter(self, record: logging.LogRecord) -> bool:
        if record.levelno >= logging.WARNING:
            return True
        return not record.name.startswith(self._prefixes)

def _setup_logging() -> None:
    level_name = (os.getenv("LOG_LEVEL") or "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)

    logging.basicConfig(
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        level=level,
        force=True,
    )

    # Silence noisy libraries (and prevent token from appearing in request logs)
    for noisy_logger in (
        "httpx",
        "httpcore",
        "telegram",
        "telegram.ext",
        "apscheduler",
    ):
        lib_logger = logging.getLogger(noisy_logger)
        lib_logger.setLevel(logging.WARNING)
        lib_logger.propagate = True

    redact_filter = _RedactBotTokenFilter(TOKEN)
    suppress_filter = _SuppressNoisyLibsFilter()
    for handler in logging.getLogger().handlers:
        handler.addFilter(suppress_filter)
        handler.addFilter(redact_filter)

_setup_logging()
logger = logging.getLogger(__name__)

def _file_size_mb(path: Path) -> float:
    try:
        return path.stat().st_size / (1024 * 1024)
    except Exception:
        return 0.0

TELEGRAM_MAX_UPLOAD_MB = float(os.getenv("TELEGRAM_MAX_UPLOAD_MB", "45"))
STARTUP_NOTIFY_CHAT_ID = int(os.getenv("STARTUP_NOTIFY_CHAT_ID") or os.getenv("SUPER_ADMIN_CHAT_ID") or "0")
SEND_STARTUP_NOTIFICATION = str(os.getenv("SEND_STARTUP_NOTIFICATION", "0")).lower() in {"1", "true", "yes"}

IPINFO_URL = "https://ipinfo.io/json"
NETWORK_INFO_CALLBACKS = {"show_private_ip", "show_public_ip"}
ADMIN_ADD_STATE_KEY = "admin_add_user_state"
ADMIN_ADD_DRAFT_KEY = "admin_add_user_draft"
ADMIN_ADD_STATE_NAME = "name"
ADMIN_ADD_STATE_CHAT_ID = "chat_id"
ADMIN_ADD_STATE_ROLE = "role"


def _startup_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("🏠 IP privada", callback_data="show_private_ip"),
                InlineKeyboardButton("🌐 IP pública", callback_data="show_public_ip"),
            ]
        ]
    )


def _get_private_ip_sync() -> str:
    """Best-effort private/source IP used for outbound LAN traffic."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        # No packets are sent; connect selects the local source address.
        sock.connect(("8.8.8.8", 80))
        return sock.getsockname()[0]
    finally:
        sock.close()


async def get_private_ip() -> str:
    try:
        return await asyncio.to_thread(_get_private_ip_sync)
    except Exception as exc:
        logger.warning("private_ip_lookup_failed error=%s", exc)
        return "No disponible"


def _get_public_ipinfo_sync() -> dict:
    request = Request(IPINFO_URL, headers={"User-Agent": "multimedia-downloader-bot/1.0"})
    with urlopen(request, timeout=8) as response:
        return json.loads(response.read().decode("utf-8"))


async def get_public_ipinfo() -> dict:
    try:
        return await asyncio.to_thread(_get_public_ipinfo_sync)
    except Exception as exc:
        logger.warning("public_ip_lookup_failed error=%s", exc)
        return {"error": str(exc)}


def format_private_ip_message(private_ip: str) -> str:
    return f"🏠 IP privada actual del bot: `{private_ip}`"


def format_public_ip_message(info: dict) -> str:
    if info.get("error"):
        return f"🌐 IP pública: No disponible ({info['error']})"

    lines = [f"🌐 IP pública actual del bot: `{info.get('ip', 'No disponible')}`"]
    details = []
    for label, key in (("Ciudad", "city"), ("Región", "region"), ("País", "country"), ("Org", "org")):
        value = info.get(key)
        if value:
            details.append(f"{label}: {value}")
    if details:
        lines.append("\n" + "\n".join(details))
    return "\n".join(lines)


async def build_network_status_message() -> str:
    private_ip, public_info = await asyncio.gather(get_private_ip(), get_public_ipinfo())
    return (
        "🤖 Bot iniciado\n\n"
        f"{format_private_ip_message(private_ip)}\n\n"
        f"{format_public_ip_message(public_info)}"
    )


async def send_startup_notification(application: Application) -> None:
    if not SEND_STARTUP_NOTIFICATION:
        logger.info("Startup notification skipped: SEND_STARTUP_NOTIFICATION disabled")
        return
    if not STARTUP_NOTIFY_CHAT_ID:
        logger.info("Startup notification skipped: STARTUP_NOTIFY_CHAT_ID/SUPER_ADMIN_CHAT_ID not configured")
        return

    try:
        await application.bot.send_message(
            chat_id=STARTUP_NOTIFY_CHAT_ID,
            text=await build_network_status_message(),
            reply_markup=_main_menu(False),
        )
        logger.info("startup_notification_sent chat_id=%s", STARTUP_NOTIFY_CHAT_ID)
    except Exception as exc:
        logger.warning("startup_notification_failed chat_id=%s error=%s", STARTUP_NOTIFY_CHAT_ID, exc)

# Ensure directories exist and have correct permissions
if not ensure_directories(DOWNLOAD_DIR, SAVED_VIDEOS_DIR):
    raise ValueError(
        f"Error: No se puede acceder a los directorios de descarga.\n"
        f"Por favor, verifica que los volúmenes de Docker estén correctamente montados:\n"
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

def _main_menu(is_admin: bool) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton("🏠 IP privada", callback_data="show_private_ip"), InlineKeyboardButton("🌐 IP pública", callback_data="show_public_ip")],
    ]
    if is_admin:
        rows.append([InlineKeyboardButton("👥 Administración de usuarios", callback_data="admin_users_menu")])
    return InlineKeyboardMarkup(rows)


def _admin_users_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ Agregar/actualizar usuario", callback_data="admin_add_user")],
        [InlineKeyboardButton("📋 Ver usuarios", callback_data="admin_list_users")],
        [InlineKeyboardButton("🚫 Ver intentos no autorizados", callback_data="admin_events")],
        [InlineKeyboardButton("⬅️ Volver", callback_data="main_menu")],
    ])


def _admin_role_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("👤 Usuario", callback_data="admin_add_role_user")],
        [InlineKeyboardButton("👑 Admin", callback_data="admin_add_role_admin")],
        [InlineKeyboardButton("❌ Cancelar", callback_data="admin_add_cancel")],
    ])


def _admin_cancel_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancelar", callback_data="admin_add_cancel")]])


def _clear_admin_add_flow(context: ContextTypes.DEFAULT_TYPE) -> None:
    context.user_data.pop(ADMIN_ADD_STATE_KEY, None)
    context.user_data.pop(ADMIN_ADD_DRAFT_KEY, None)


def _role_label(is_admin: bool) -> str:
    return "admin" if is_admin else "usuario"


async def _show_main_menu(chat_id: int, bot, edit_message=None) -> None:
    admin = await is_super_admin(chat_id)
    text = (
        "🎥 *Multimedia Downloader Bot*\n\n"
        "Envíame un enlace de Instagram, Facebook, TikTok, YouTube, Dailymotion o FlixGaze "
        "y te preguntaré qué quieres hacer con él."
    )
    if admin:
        text += "\n\n👑 Tienes habilitado el menú de administración de usuarios."
    if edit_message:
        await edit_message.edit_text(text, reply_markup=_main_menu(admin), parse_mode="Markdown")
    else:
        await bot.send_message(chat_id=chat_id, text=text, reply_markup=_main_menu(admin), parse_mode="Markdown")


async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Admin command to add authorized users. Only super admins can use this."""
    if not await is_super_admin(update.effective_chat.id):
        await handle_unauthorized_user(update, "/admin")
        return
    
    if not context.args:
        await update.message.reply_text("👥 Administración de usuarios", reply_markup=_admin_users_menu())
        return

    if context.args[0].lower() == "remove":
        try:
            removed = await remove_authorized_user(int(context.args[1]))
            await update.message.reply_text("✅ Usuario removido." if removed else "⚠️ No se removió el usuario (no existe o es admin semilla).")
        except (IndexError, ValueError):
            await update.message.reply_text("Uso: /admin remove <telegram_id>")
        return

    try:
        chat_id = int(context.args[0])
        username = context.args[1] if len(context.args) > 1 else None
        is_super = context.args[2].lower() in {"true", "admin", "1", "yes"} if len(context.args) > 2 else False
        await add_authorized_user(chat_id, username, is_super)
        await update.message.reply_text(f"✅ Usuario {chat_id} guardado como {_role_label(is_super)}.")
    except ValueError:
        await update.message.reply_text("Uso: /admin <telegram_id> [username] [user|admin]\nEjemplo: /admin 123456789 rafa admin")

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

    await _show_main_menu(update.effective_chat.id, context.bot)

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
        "- YouTube (videos)\n"
        "- Dailymotion (videos públicos)\n"
        "- FlixGaze (stream HLS del reproductor)"
    )

async def handle_admin_add_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Handle step-by-step admin user creation from chat text."""
    state = context.user_data.get(ADMIN_ADD_STATE_KEY)
    if not state:
        return False

    if not await is_super_admin(update.effective_chat.id):
        _clear_admin_add_flow(context)
        await handle_unauthorized_user(update, "admin_add_flow")
        return True

    text = (update.message.text or "").strip()
    if text.lower() in {"cancelar", "cancel", "/cancel"}:
        _clear_admin_add_flow(context)
        await update.message.reply_text("Operación cancelada.", reply_markup=_admin_users_menu())
        return True

    draft = context.user_data.setdefault(ADMIN_ADD_DRAFT_KEY, {})

    if state == ADMIN_ADD_STATE_NAME:
        if not text:
            await update.message.reply_text("Mándame un nombre o alias válido.", reply_markup=_admin_cancel_keyboard())
            return True
        draft["name"] = text.lstrip("@")
        context.user_data[ADMIN_ADD_STATE_KEY] = ADMIN_ADD_STATE_CHAT_ID
        await update.message.reply_text(
            "Perfecto. Ahora envíame el *Telegram ID numérico* del usuario.\n\n"
            "Nota: para autorizar de forma confiable Telegram requiere el ID; el @username por sí solo no alcanza.",
            reply_markup=_admin_cancel_keyboard(),
            parse_mode="Markdown",
        )
        return True

    if state == ADMIN_ADD_STATE_CHAT_ID:
        try:
            chat_id = int(text)
        except ValueError:
            await update.message.reply_text(
                "Ese valor no parece un Telegram ID numérico. Envíame solo números, por ejemplo: `123456789`.",
                reply_markup=_admin_cancel_keyboard(),
                parse_mode="Markdown",
            )
            return True
        draft["chat_id"] = chat_id
        context.user_data[ADMIN_ADD_STATE_KEY] = ADMIN_ADD_STATE_ROLE
        await update.message.reply_text(
            f"Listo. ¿Qué rol tendrá `{chat_id}`?",
            reply_markup=_admin_role_keyboard(),
            parse_mode="Markdown",
        )
        return True

    return False


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if await handle_admin_add_text(update, context):
        return
    await update.message.reply_text("Envíame un enlace de video válido o usa /start para ver el menú.")


async def handle_url(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle incoming URLs and show action options."""
    if not await is_user_authorized(update.effective_chat.id):
        await handle_unauthorized_user(update)
        return

    url = update.message.text
    chat_id = update.effective_chat.id
    username = update.effective_user.username if update.effective_user else None
    logger.info(
        "url_received chat_id=%s username=%s url=%s",
        chat_id,
        username,
        _sanitize_url_for_log(url),
    )
    
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

async def _send_users_list(query) -> None:
    users = await list_authorized_users()
    if not users:
        await query.edit_message_text("No hay usuarios autorizados.", reply_markup=_admin_users_menu())
        return
    lines = ["👥 *Usuarios autorizados*", ""]
    for user in users:
        username = f"@{user.username}" if user.username else "sin username"
        lines.append(f"• `{user.chat_id}` — {username} — {_role_label(user.is_super_admin)}")
    await query.edit_message_text("\n".join(lines), reply_markup=_admin_users_menu(), parse_mode="Markdown")


async def _send_events_list(query) -> None:
    events = await get_unauthorized_events(10)
    if not events:
        await query.edit_message_text("No hay intentos no autorizados registrados.", reply_markup=_admin_users_menu())
        return
    lines = ["🚫 *Últimos intentos no autorizados*", ""]
    for event in events:
        username = f"@{event.username}" if event.username else "sin username"
        lines.append(f"• `{event.chat_id}` — {username} — `{event.command}`")
    await query.edit_message_text("\n".join(lines), reply_markup=_admin_users_menu(), parse_mode="Markdown")


async def _handle_admin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    query = update.callback_query
    chat_id = query.message.chat_id
    if query.data == "main_menu":
        await _show_main_menu(chat_id, context.bot, edit_message=query.message)
        return True
    if not query.data.startswith("admin_"):
        return False
    if not await is_super_admin(chat_id):
        await query.answer("Solo admins pueden usar este menú.", show_alert=True)
        return True
    if query.data == "admin_users_menu":
        await query.edit_message_text("👥 *Administración de usuarios*", reply_markup=_admin_users_menu(), parse_mode="Markdown")
    elif query.data == "admin_add_user":
        context.user_data[ADMIN_ADD_STATE_KEY] = ADMIN_ADD_STATE_NAME
        context.user_data[ADMIN_ADD_DRAFT_KEY] = {}
        await query.edit_message_text(
            "➕ *Agregar/actualizar usuario*\n\n"
            "Primero envíame el *nombre o alias* de la persona.",
            reply_markup=_admin_cancel_keyboard(),
            parse_mode="Markdown",
        )
    elif query.data == "admin_add_cancel":
        _clear_admin_add_flow(context)
        await query.edit_message_text("Operación cancelada.", reply_markup=_admin_users_menu())
    elif query.data in {"admin_add_role_user", "admin_add_role_admin"}:
        draft = context.user_data.get(ADMIN_ADD_DRAFT_KEY) or {}
        if context.user_data.get(ADMIN_ADD_STATE_KEY) != ADMIN_ADD_STATE_ROLE or "chat_id" not in draft:
            await query.answer("No hay un alta de usuario en curso.", show_alert=True)
            return True
        is_super = query.data == "admin_add_role_admin"
        await add_authorized_user(int(draft["chat_id"]), draft.get("name"), is_super)
        _clear_admin_add_flow(context)
        await query.edit_message_text(
            f"✅ Usuario `{draft['chat_id']}` guardado como *{_role_label(is_super)}*.\n"
            f"Nombre/alias: {draft.get('name') or 'sin nombre'}",
            reply_markup=_admin_users_menu(),
            parse_mode="Markdown",
        )
    elif query.data == "admin_list_users":
        await _send_users_list(query)
    elif query.data == "admin_events":
        await _send_events_list(query)
    return True


def _format_progress(info: dict) -> str:
    total = info.get("total_bytes")
    downloaded = info.get("downloaded_bytes") or 0
    eta = info.get("eta")
    speed = info.get("speed")
    if total:
        pct = min(100.0, downloaded * 100 / total)
        text = f"⬇️ Descargando video... {pct:.1f}%"
    else:
        text = f"⬇️ Descargando video... {downloaded / (1024 * 1024):.1f} MB"
    if eta:
        text += f"\nETA: {eta}s"
    if speed:
        text += f" · {speed / (1024 * 1024):.1f} MB/s"
    return text


async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle button callbacks."""
    if not await is_user_authorized(update.callback_query.message.chat_id):
        await update.callback_query.answer("No estás autorizado para usar este bot.")
        await update.callback_query.message.delete()
        return

    query = update.callback_query
    await query.answer()

    if await _handle_admin_callback(update, context):
        return

    if query.data in NETWORK_INFO_CALLBACKS:
        chat = update.effective_chat
        if chat is None:
            return
        chat_id = chat.id
        if query.data == "show_private_ip":
            text = format_private_ip_message(await get_private_ip())
        else:
            text = format_public_ip_message(await get_public_ipinfo())
        await context.bot.send_message(chat_id=chat_id, text=text)
        return
    
    url = context.user_data.get('current_url')
    if not url:
        await query.edit_message_text("❌ Lo siento, hubo un error. Por favor, envía el enlace nuevamente.")
        return

    chat_id = query.message.chat_id
    username = update.effective_user.username if update.effective_user else None
    action = query.data
    logger.info(
        "action_selected chat_id=%s username=%s action=%s url=%s",
        chat_id,
        username,
        action,
        _sanitize_url_for_log(url),
    )
    
    message = await query.edit_message_text("⏳ Procesando el enlace...")
    
    try:
        # Choose directory based on action
        output_dir = SAVED_VIDEOS_DIR if query.data in ["save", "save_and_send"] else DOWNLOAD_DIR
        
        await message.edit_text("⬇️ Descargando video... 0%")
        last_progress = {"percent": -1}

        async def progress_callback(info: dict) -> None:
            if info.get("status") not in {"downloading", "finished"}:
                return
            total = info.get("total_bytes")
            downloaded = info.get("downloaded_bytes") or 0
            percent = int(downloaded * 100 / total) if total else 0
            if info.get("status") == "finished":
                percent = 100
            # Avoid Telegram rate limits: update every 5% plus completion.
            if percent < 100 and percent - last_progress["percent"] < 5:
                return
            last_progress["percent"] = percent
            try:
                await message.edit_text(_format_progress(info))
            except Exception:
                pass

        success, status_msg, video_path = await download_video(url, output_dir, progress_callback=progress_callback)
        
        if not success:
            raise Exception(status_msg)
        
        if query.data == "send":
            # Solo enviar
            await message.edit_text("📤 Enviando video...")
            # Make it Telegram-friendly (avoid still-frame+audio issues)
            ok, _, send_path = await transcode_to_telegram_mp4(video_path)
            if not ok:
                send_path = video_path

            size_mb = _file_size_mb(send_path)
            if size_mb > TELEGRAM_MAX_UPLOAD_MB:
                # Clean up (send-only should not keep large files)
                try:
                    if send_path != video_path:
                        send_path.unlink()
                    video_path.unlink()
                except Exception:
                    pass
                logger.warning(
                    "action_failed chat_id=%s username=%s action=%s error=file_too_large size_mb=%.2f limit_mb=%.2f",
                    chat_id,
                    username,
                    action,
                    size_mb,
                    TELEGRAM_MAX_UPLOAD_MB,
                )
                await message.edit_text(
                    f"⚠️ El video pesa {size_mb:.2f} MB y excede el límite de envío del bot (≈{TELEGRAM_MAX_UPLOAD_MB:.0f} MB).\n"
                    "Usa la opción 'Descargar y guardar' para conservarlo en el servidor."
                )
                return

            try:
                await context.bot.send_video(
                    chat_id=chat_id,
                    video=send_path,
                    caption=f"📹 Video descargado"
                )
            except BadRequest as e:
                if "Request Entity Too Large" in str(e):
                    # Clean up
                    try:
                        if send_path != video_path:
                            send_path.unlink()
                        video_path.unlink()
                    except Exception:
                        pass
                    logger.warning(
                        "action_failed chat_id=%s username=%s action=%s error=telegram_413 size_mb=%.2f",
                        chat_id,
                        username,
                        action,
                        size_mb,
                    )
                    await message.edit_text(
                        "⚠️ Telegram rechazó el envío por tamaño (413).\n"
                        "Usa la opción 'Descargar y guardar' para conservarlo en el servidor."
                    )
                    return
                raise
            # Clean up
            try:
                if send_path != video_path:
                    send_path.unlink()
            finally:
                video_path.unlink()
            await message.delete()
            logger.info(
                "action_success chat_id=%s username=%s action=%s result=sent",
                chat_id,
                username,
                action,
            )
        elif query.data == "save":
            # Solo guardar
            await message.edit_text(
                f"✅ Video guardado exitosamente como:\n"
                f"`{video_path.name}`"
            )
            logger.info(
                "action_success chat_id=%s username=%s action=%s result=saved file=%s",
                chat_id,
                username,
                action,
                video_path.name,
            )
        else:  # save_and_send
            # Guardar y enviar
            await message.edit_text("📤 Enviando video...")
            ok, _, send_path = await transcode_to_telegram_mp4(video_path)
            if ok and send_path != video_path:
                # Replace saved file with Telegram-friendly one to avoid keeping two copies
                try:
                    video_path.unlink()
                except Exception:
                    pass
                video_path = send_path

            size_mb = _file_size_mb(video_path)
            if size_mb > TELEGRAM_MAX_UPLOAD_MB:
                # Keep file (it's in SAVED_VIDEOS_DIR)
                logger.warning(
                    "action_failed chat_id=%s username=%s action=%s error=file_too_large size_mb=%.2f limit_mb=%.2f file=%s",
                    chat_id,
                    username,
                    action,
                    size_mb,
                    TELEGRAM_MAX_UPLOAD_MB,
                    video_path.name,
                )
                await message.edit_text(
                    f"✅ Video guardado como:\n`{video_path.name}`\n\n"
                    f"⚠️ No se pudo reenviar: pesa {size_mb:.2f} MB y excede el límite de Telegram (≈{TELEGRAM_MAX_UPLOAD_MB:.0f} MB)."
                )
                return

            try:
                await context.bot.send_video(
                    chat_id=chat_id,
                    video=video_path,
                    caption=f"📹 Video guardado como:\n`{video_path.name}`"
                )
            except BadRequest as e:
                if "Request Entity Too Large" in str(e):
                    logger.warning(
                        "action_failed chat_id=%s username=%s action=%s error=telegram_413 size_mb=%.2f file=%s",
                        chat_id,
                        username,
                        action,
                        size_mb,
                        video_path.name,
                    )
                    await message.edit_text(
                        f"✅ Video guardado como:\n`{video_path.name}`\n\n"
                        "⚠️ Telegram rechazó el envío por tamaño (413)."
                    )
                    return
                raise
            await message.edit_text(
                f"✅ Video guardado y enviado exitosamente como:\n"
                f"`{video_path.name}`"
            )
            logger.info(
                "action_success chat_id=%s username=%s action=%s result=saved_and_sent file=%s",
                chat_id,
                username,
                action,
                video_path.name,
            )
            
    except Exception as e:
        logger.warning(
            "action_failed chat_id=%s username=%s action=%s error=%s",
            query.message.chat_id,
            update.effective_user.username if update.effective_user else None,
            query.data,
            str(e),
        )
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
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
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
        await send_startup_notification(application)
        
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