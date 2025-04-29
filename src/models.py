from datetime import datetime
from typing import Optional, AsyncGenerator
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy import Column, Integer, String, Boolean, DateTime, Index
from sqlalchemy.orm import sessionmaker
from contextlib import asynccontextmanager
from pydantic import BaseModel
import bleach
from pathlib import Path

# SQLAlchemy Models
Base = declarative_base()

class AuthorizedUser(Base):
    __tablename__ = "authorized_users"
    
    chat_id = Column(Integer, primary_key=True)
    username = Column(String, nullable=True)
    is_super_admin = Column(Boolean, default=False)
    added_at = Column(DateTime, default=datetime.utcnow)
    
    # Add indexes for faster lookups
    __table_args__ = (
        Index('idx_is_super_admin', 'is_super_admin'),
    )

class UnauthorizedEvent(Base):
    __tablename__ = "unauthorized_events"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    chat_id = Column(Integer, nullable=False)
    username = Column(String, nullable=True)
    command = Column(String, nullable=False)
    timestamp = Column(DateTime, default=datetime.utcnow)
    
    # Add indexes for faster lookups
    __table_args__ = (
        Index('idx_chat_id', 'chat_id'),
        Index('idx_timestamp', 'timestamp'),
    )

# Pydantic Schemas
class UserBase(BaseModel):
    chat_id: int
    username: Optional[str] = None
    
    class Config:
        orm_mode = True

class UserCreate(UserBase):
    is_super_admin: bool = False

class User(UserBase):
    is_super_admin: bool
    added_at: datetime

class EventBase(BaseModel):
    chat_id: int
    username: Optional[str] = None
    command: str
    
    class Config:
        orm_mode = True

class Event(EventBase):
    id: int
    timestamp: datetime

# Database configuration and session management
class Database:
    def __init__(self, db_path: Path):
        self.engine = create_async_engine(
            f"sqlite+aiosqlite:///{db_path}",
            echo=False,
            future=True
        )
        self.async_session = sessionmaker(
            self.engine,
            class_=AsyncSession,
            expire_on_commit=False
        )

    async def initialize(self):
        """Create all tables"""
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    @asynccontextmanager
    async def session(self) -> AsyncGenerator[AsyncSession, None]:
        """Get a database session with proper async context management"""
        session: AsyncSession = self.async_session()
        try:
            yield session
        finally:
            await session.close()

# Input sanitization functions
def sanitize_text(text: str) -> str:
    """Sanitize text input to prevent XSS"""
    return bleach.clean(text, tags=[], strip=True)

def sanitize_command(command: str) -> str:
    """Sanitize command input to prevent command injection"""
    # Remove any shell special characters
    return ''.join(c for c in command if c.isalnum() or c in '_-/.')

def sanitize_path(path: str) -> str:
    """Sanitize file paths to prevent path traversal"""
    from slugify import slugify
    # Convert to safe path and remove any potential traversal attempts
    return slugify(path, separator='_')