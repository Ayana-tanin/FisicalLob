import datetime
import logging
from sqlalchemy import select, update
from sqlalchemy.exc import SQLAlchemyError
from db_base import SessionLocal
from models import User, Job

logger = logging.getLogger(__name__)

# Временное хранилище вакансий (можно заменить на запросы к БД)
user_jobs = {}

# Лимит бесплатных публикаций в день
DAILY_LIMIT = 1


def init_db():
    """
    Инициализация базы данных. Создает все таблицы, если они не существуют.
    Эта функция вызывается при запуске бота.
    """
    from db_base import Base, engine
    try:
        Base.metadata.create_all(bind=engine)
        logger.info("База данных успешно инициализирована")
    except SQLAlchemyError as e:
        logger.error(f"Ошибка при инициализации базы данных: {str(e)}")
        raise


def insert_user(user_id: int, username: str) -> None:
    """
    Создает запись о пользователе в базе данных, если она не существует.

    Args:
        user_id: Telegram ID пользователя
        username: Username пользователя
    """
    try:
        with SessionLocal() as session:
            # Проверяем существование пользователя
            stmt = select(User).where(User.telegram_id == user_id)
            user = session.execute(stmt).scalar_one_or_none()

            if not user:
                # Создаем нового пользователя
                user = User(telegram_id=user_id, username=username)
                session.add(user)
                session.commit()
                logger.info(f"Добавлен новый пользователь: {user_id}")
    except SQLAlchemyError as e:
        logger.error(f"Ошибка при добавлении пользователя {user_id}: {str(e)}")

def can_post_more(user_id: int) -> bool:
    with SessionLocal() as session:
        user = session.query(User).filter_by(telegram_id=user_id).first()
        if not user:
            return False
        if user.telegram_id in user_jobs and len(user_jobs[user.telegram_id]) >= DAILY_LIMIT:
            return user.can_post
        return True

def mark_user_allowed(user_id: int) -> None:
    with SessionLocal() as session:
        user = session.query(User).filter_by(telegram_id=user_id).first()
        if user:
            user.can_post = True
            session.commit()

def get_user_jobs(user_id: int) -> list[str]:
    return user_jobs.get(user_id, [])

def delete_user_job(user_id: int, index: int) -> bool:
    if user_id in user_jobs and 0 <= index < len(user_jobs[user_id]):
        user_jobs[user_id].pop(index)
        return True
    return False

def update_invite_count(user_id: int):
    with SessionLocal() as session:
        user = session.query(User).filter_by(telegram_id=user_id).first()
        if user:
            user.invites += 1
            session.commit()


def save_job(user_id: int, job_text: str) -> None:
    """
    Сохраняет текст вакансии в памяти для данного пользователя.
    """
    user_jobs.setdefault(user_id, []).append(job_text)

def delete_job_by_id(user_id: int, index: int) -> bool:
    """
    Удаляет вакансию по индексу, возвращает True при успехе.
    """
    from .db_connection import delete_user_job
    return delete_user_job(user_id, index)

