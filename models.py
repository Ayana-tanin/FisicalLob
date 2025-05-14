from sqlalchemy import (
    Column, Integer, BigInteger, ForeignKey,
    DateTime, Boolean, Text
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

    jobs = relationship("Job", back_populates="user", cascade="all, delete-orphan")

class Job(Base):
    __tablename__ = "jobs"
    id           = Column(Integer, primary_key=True)
    user_id = Column(BigInteger, ForeignKey("users.telegram_id", ondelete="CASCADE"), nullable=False)
    message_id   = Column(BigInteger, nullable=False)
    all_info     = Column(JSONB, nullable=False)
    created_at   = Column(DateTime(timezone=True), server_default=func.now())

    user = relationship("User", back_populates="jobs")
