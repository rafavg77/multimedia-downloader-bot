import logging
import os
from pathlib import Path
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from dotenv import load_dotenv
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from models import Base, AuthorizedUser, UnauthorizedEvent, UserCreate, Event, EventBase, sanitize_text, sanitize_command

logger = logging.getLogger(__name__)
load_dotenv()

SUPER_ADMIN_CHAT_ID = int(os.getenv("SUPER_ADMIN_CHAT_ID", "0") or "0")
DB_PATH = Path(os.getenv("DB_PATH", "/data/db/users.db")).resolve()
DATABASE_URL = os.getenv("DATABASE_URL", "").strip()

if not DATABASE_URL:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    DATABASE_URL = f"sqlite+aiosqlite:///{DB_PATH}"
elif DATABASE_URL.startswith("postgresql://"):
    DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://", 1)

engine = create_async_engine(DATABASE_URL, echo=False, future=True)
async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


@asynccontextmanager
async def session_scope() -> AsyncGenerator[AsyncSession, None]:
    session: AsyncSession = async_session()
    try:
        yield session
    finally:
        await session.close()


async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    if SUPER_ADMIN_CHAT_ID:
        await add_authorized_user(SUPER_ADMIN_CHAT_ID, None, True)
        logger.info("super_admin_seeded chat_id=%s", SUPER_ADMIN_CHAT_ID)


async def is_user_authorized(chat_id: int) -> bool:
    async with session_scope() as session:
        result = await session.execute(select(AuthorizedUser.chat_id).where(AuthorizedUser.chat_id == chat_id))
        return result.scalar_one_or_none() is not None


async def is_super_admin(chat_id: int) -> bool:
    async with session_scope() as session:
        result = await session.execute(
            select(AuthorizedUser.chat_id).where(
                AuthorizedUser.chat_id == chat_id,
                AuthorizedUser.is_super_admin.is_(True),
            )
        )
        return result.scalar_one_or_none() is not None


async def add_authorized_user(chat_id: int, username: str | None = None, is_super_admin: bool = False):
    user_data = UserCreate(
        chat_id=chat_id,
        username=sanitize_text(username.lstrip("@")) if username else None,
        is_super_admin=is_super_admin,
    )
    async with session_scope() as session:
        user = await session.get(AuthorizedUser, user_data.chat_id)
        if user:
            user.username = user_data.username
            user.is_super_admin = user_data.is_super_admin
        else:
            session.add(AuthorizedUser(**user_data.dict()))
        await session.commit()


async def remove_authorized_user(chat_id: int) -> bool:
    if SUPER_ADMIN_CHAT_ID and chat_id == SUPER_ADMIN_CHAT_ID:
        return False
    async with session_scope() as session:
        result = await session.execute(delete(AuthorizedUser).where(AuthorizedUser.chat_id == chat_id))
        await session.commit()
        return bool(result.rowcount)


async def list_authorized_users() -> list[AuthorizedUser]:
    async with session_scope() as session:
        result = await session.execute(select(AuthorizedUser).order_by(AuthorizedUser.is_super_admin.desc(), AuthorizedUser.added_at.desc()))
        return list(result.scalars().all())


async def get_authorized_user(chat_id: int) -> AuthorizedUser | None:
    async with session_scope() as session:
        return await session.get(AuthorizedUser, chat_id)


async def log_unauthorized_attempt(chat_id: int, username: str | None, command: str):
    event_data = EventBase(
        chat_id=chat_id,
        username=sanitize_text(username) if username else None,
        command=sanitize_command(command),
    )
    async with session_scope() as session:
        session.add(UnauthorizedEvent(**event_data.dict()))
        await session.commit()


async def get_unauthorized_events(limit: int = 100) -> list[Event]:
    async with session_scope() as session:
        result = await session.execute(select(UnauthorizedEvent).order_by(UnauthorizedEvent.timestamp.desc()).limit(limit))
        return [Event.from_orm(event) for event in result.scalars().all()]
