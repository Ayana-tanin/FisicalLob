import datetime
import logging
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from db_base import SessionLocal
from models import User, Job
from sqlalchemy import func, and_

logger = logging.getLogger(__name__)


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


def update_invite_count(user_id: int):
    with SessionLocal() as session:
        user = session.query(User).filter_by(telegram_id=user_id).first()
        if user:
            user.invites += 1
            session.commit()

def allow_user_posting(user_identifier: str) -> (bool, str):
    """
    Разрешить пользователю публиковать вакансии (can_post = True).
    user_identifier — либо username без @, либо telegram_id (int в строке).
    Возвращает кортеж (успех, сообщение).
    """
    try:
        with SessionLocal() as session:
            if user_identifier.startswith("@"):
                username = user_identifier[1:]
                user = session.execute(select(User).where(User.username == username)).scalar_one_or_none()
                if not user:
                    return False, f"Пользователь с username @{username} не найден."
            else:
                if user_identifier.isdigit():
                    user = session.query(User).filter_by(telegram_id=int(user_identifier)).first()
                    if not user:
                        return False, f"Пользователь с ID {user_identifier} не найден."
                else:
                    return False, "Некорректный user_id или username."

            user.can_post = True
            session.commit()
            return True, f"Пользователю @{user.username} (ID {user.telegram_id}) разрешена публикация вакансий."
    except SQLAlchemyError as e:
        logger.error(f"Ошибка базы при allow_user_posting: {e}")
        return False, "Ошибка при обращении к базе данных."


def save_job_db(user_id: int, message_id: int, all_info: dict) -> bool:
    try:
        with SessionLocal() as session:
            job = Job(user_id=user_id, message_id=message_id, all_info=all_info)
            session.add(job)
            session.commit()
        return True
    except SQLAlchemyError as e:
        logger.error(f"Ошибка при сохранении вакансии: {e}")
        return False

def get_user_jobs_db(user_id: int) -> list[Job]:
    try:
        with SessionLocal() as session:
            jobs = session.query(Job).filter_by(user_id=user_id).order_by(Job.created_at.desc()).all()
        return jobs
    except SQLAlchemyError as e:
        logger.error(f"Ошибка при получении вакансий: {e}")
        return []

def delete_job_and_get_message(user_id: int, index: int) -> tuple[int | None, bool]:
    try:
        with SessionLocal() as session:
            jobs = session.query(Job).filter_by(user_id=user_id).order_by(Job.created_at.desc()).all()
            if index < 0 or index >= len(jobs):
                return None, False
            job = jobs[index]
            message_id = job.message_id
            session.delete(job)
            session.commit()
            return message_id, True
    except SQLAlchemyError as e:
        logger.error(f"Ошибка при удалении вакансии: {e}")
        return None, False

def can_post_more(user_id: int, daily_limit: int = 1) -> bool:
    try:
        with SessionLocal() as session:
            user = session.query(User).filter_by(telegram_id=user_id).first()
            if not user:
                return False  # пользователь не найден — запретить

            # Если у пользователя can_post = True — разрешаем всегда
            if user.can_post:
                return True

            # Считаем, сколько вакансий пользователь опубликовал сегодня
            today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
            count_today = session.query(func.count(Job.id)).filter(
                and_(
                    Job.user_id == user_id,
                    Job.created_at >= today_start
                )
            ).scalar()

            return count_today < daily_limit
    except Exception as e:
        logger.error(f"Ошибка при проверке can_post_more: {e}")
        return False
