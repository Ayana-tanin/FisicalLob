from db_base import SessionLocal
from models import *

from db_base import engine
from models import Base

def init_db():
    Base.metadata.create_all(bind=engine)

# Пользователь
def insert_user(user_id: int, username: str) -> None:
    with SessionLocal() as session:
        user = session.query(User).filter_by(telegram_id=user_id).first()
        if not user:
            user = User(telegram_id=user_id, username=username)
            session.add(user)
            session.commit()

def can_post_more(user_id: int) -> bool:
    with SessionLocal() as session:
        user = session.query(User).filter_by(telegram_id=user_id).first()
        return user.can_post if user else False

def mark_user_allowed(user_id: int) -> None:
    with SessionLocal() as session:
        user = session.query(User).filter_by(telegram_id=user_id).first()
        if user:
            user.can_post = True
            session.commit()

def update_invite_count(user_id: int):
    with SessionLocal() as session:
        user = session.query(User).filter_by(telegram_id=user_id).first()
        if user:
            user.invites += 1
            session.commit()

# Вакансии
def save_job(user_id: int, message_id: int, all_info: dict) -> None:
    with SessionLocal() as session:
        job = Job(user_id=user_id, message_id=message_id, all_info=all_info)
        session.add(job)
        session.commit()

def get_user_jobs(user_id: int) -> list[Job]:
    with SessionLocal() as session:
        user = session.query(User).filter_by(telegram_id=user_id).first()
        return user.jobs if user else []

def delete_job_by_id(job_id: int) -> Job | None:
    with SessionLocal() as session:
        job = session.query(Job).filter_by(id=job_id).first()
        if job:
            session.delete(job)
            session.commit()
            return job
        return None
