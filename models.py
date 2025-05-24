from sqlalchemy import (
    Column, Integer, BigInteger, ForeignKey,
    DateTime, Boolean, Text, JSON, UniqueConstraint
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from db_base import Base

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    telegram_id = Column(BigInteger, unique=True, nullable=False)
    username = Column(Text)
    can_post = Column(Boolean, default=False)
    invites = Column(Integer, default=0)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    can_post_until = Column(DateTime, nullable=True)  # до какой даты можно постить без ограничений
    allowed_posts = Column(Integer, default=0)

    jobs = relationship("Job", back_populates="user", cascade="all, delete-orphan")
    invited_users = relationship("InvitedUser", back_populates="inviter", cascade="all, delete-orphan")

class Job(Base):
    __tablename__ = "jobs"
    id           = Column(Integer, primary_key=True)
    user_id = Column(BigInteger, ForeignKey("users.telegram_id", ondelete="CASCADE"), nullable=False)
    message_id   = Column(BigInteger, nullable=False)
    all_info     = Column(JSON, nullable=False)
    created_at   = Column(DateTime(timezone=True), server_default=func.now())

    user = relationship("User", back_populates="jobs")

class InvitedUser(Base):
    __tablename__ = "invited_users"
    id = Column(Integer, primary_key=True)
    inviter_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    invited_id = Column(BigInteger, nullable=False)  # Telegram ID приглашенного
    invited_at = Column(DateTime(timezone=True), server_default=func.now())
    is_active = Column(Boolean, default=True)  # активен ли пользователь в группе
    
    inviter = relationship("User", back_populates="invited_users")
    
    __table_args__ = (
        UniqueConstraint('inviter_id', 'invited_id', name='unique_invite'),
    )
