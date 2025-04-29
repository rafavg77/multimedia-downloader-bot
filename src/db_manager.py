import logging
import os
from pathlib import Path
from dotenv import load_dotenv
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import datetime

from models import (
    Database, AuthorizedUser, UnauthorizedEvent,
    UserCreate, User, Event, EventBase,
    sanitize_text, sanitize_command
)

logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()
SUPER_ADMIN_CHAT_ID = int(os.getenv('SUPER_ADMIN_CHAT_ID', '0'))

# Database path
DB_PATH = Path(__file__).parent / "users.db"
db = Database(DB_PATH)

async def init_db():
    """Initialize the database and create tables."""
    await db.initialize()
    
    # Add super admin if not exists
    if SUPER_ADMIN_CHAT_ID:
        async with db.session() as session:
            stmt = select(AuthorizedUser).where(AuthorizedUser.chat_id == SUPER_ADMIN_CHAT_ID)
            result = await session.execute(stmt)
            super_admin = result.scalar()
            
            if not super_admin:
                super_admin = AuthorizedUser(
                    chat_id=SUPER_ADMIN_CHAT_ID,
                    is_super_admin=True
                )
                session.add(super_admin)
                await session.commit()

async def is_user_authorized(chat_id: int) -> bool:
    """Check if a user is authorized to use the bot."""
    async with db.session() as session:
        stmt = select(AuthorizedUser).where(AuthorizedUser.chat_id == chat_id)
        result = await session.execute(stmt)
        return result.scalar() is not None

async def is_super_admin(chat_id: int) -> bool:
    """Check if a user is a super admin."""
    async with db.session() as session:
        stmt = select(AuthorizedUser).where(
            AuthorizedUser.chat_id == chat_id,
            AuthorizedUser.is_super_admin == True
        )
        result = await session.execute(stmt)
        return result.scalar() is not None

async def add_authorized_user(chat_id: int, username: str = None, is_super_admin: bool = False):
    """Add a new authorized user to the database."""
    # Validate and sanitize input
    user_data = UserCreate(
        chat_id=chat_id,
        username=sanitize_text(username) if username else None,
        is_super_admin=is_super_admin
    )
    
    async with db.session() as session:
        # Check if user exists
        stmt = select(AuthorizedUser).where(AuthorizedUser.chat_id == user_data.chat_id)
        result = await session.execute(stmt)
        user = result.scalar()
        
        if user:
            # Update existing user
            user.username = user_data.username
            user.is_super_admin = user_data.is_super_admin
        else:
            # Create new user
            user = AuthorizedUser(**user_data.dict())
            session.add(user)
        
        await session.commit()

async def log_unauthorized_attempt(chat_id: int, username: str | None, command: str):
    """Log an unauthorized attempt to use the bot."""
    # Validate and sanitize input
    event_data = EventBase(
        chat_id=chat_id,
        username=sanitize_text(username) if username else None,
        command=sanitize_command(command)
    )
    
    async with db.session() as session:
        event = UnauthorizedEvent(**event_data.dict())
        session.add(event)
        await session.commit()

async def get_user_count() -> int:
    """Get the total number of authorized users."""
    async with db.session() as session:
        result = await session.execute(select(AuthorizedUser))
        return len(result.scalars().all())

async def get_unauthorized_events(limit: int = 100) -> list[Event]:
    """Get recent unauthorized access attempts."""
    async with db.session() as session:
        stmt = select(UnauthorizedEvent).order_by(UnauthorizedEvent.timestamp.desc()).limit(limit)
        result = await session.execute(stmt)
        events = result.scalars().all()
        return [Event.from_orm(event) for event in events]