from datetime import datetime
from typing import Optional
from sqlalchemy.orm import declarative_base
from sqlalchemy import BigInteger, Boolean, Column, DateTime, Index, Integer, String
from pydantic import BaseModel
import bleach

Base = declarative_base()


class AuthorizedUser(Base):
    __tablename__ = "authorized_users"

    chat_id = Column(BigInteger, primary_key=True)
    username = Column(String, nullable=True)
    is_super_admin = Column(Boolean, default=False, nullable=False)
    added_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    __table_args__ = (Index("idx_authorized_users_is_super_admin", "is_super_admin"),)


class UnauthorizedEvent(Base):
    __tablename__ = "unauthorized_events"

    id = Column(Integer, primary_key=True, autoincrement=True)
    chat_id = Column(BigInteger, nullable=False)
    username = Column(String, nullable=True)
    command = Column(String, nullable=False)
    timestamp = Column(DateTime, default=datetime.utcnow, nullable=False)

    __table_args__ = (
        Index("idx_unauthorized_events_chat_id", "chat_id"),
        Index("idx_unauthorized_events_timestamp", "timestamp"),
    )


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


def sanitize_text(text: str) -> str:
    return bleach.clean(text, tags=[], strip=True).strip()


def sanitize_command(command: str) -> str:
    return bleach.clean(command or "", tags=[], strip=True)[:500]
