import asyncio
import logging
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from config import BOT_TOKEN
from db_connection import init_db

# Настройка логирования с более подробной информацией
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


# Railway специфичная функция для проверки переменных окружения
def check_environment():
    """Проверяет критически важные переменные окружения"""
    import os

    required_vars = ["BOT_TOKEN", "DATABASE_URL"]
    missing = [var for var in required_vars if not os.getenv(var)]

    if missing:
        logger.critical(f"Отсутствуют следующие переменные окружения: {', '.join(missing)}")
        logger.critical("Добавьте эти переменные в настройках проекта на Railway.app")
        return False
    return True


async def main():
    """
    Основная функция, инициализирует бота и запускает его.
    """
    # Проверяем переменные окружения перед запуском
    if not check_environment():
        logger.critical("Критические переменные окружения отсутствуют. Бот не может быть запущен.")
        return

    try:
        # Инициализация базы данных
        logger.info("Инициализация базы данных...")
        init_db()

        # Создание экземпляра бота
        logger.info("Создание экземпляра бота...")
        bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))

        # Создание диспетчера
        dp = Dispatcher(storage=MemoryStorage())

        # Импортируем роутер здесь, чтобы избежать циклического импорта
        from handlers import router
        dp.include_router(router)

        # Регистрация обработчика завершения
        async def on_shutdown(dispatcher):
            logger.warning("Завершение работы бота...")
            # Здесь можно добавить код для корректного завершения работы

        dp.shutdown.register(on_shutdown)

        # Запуск бота
        logger.info("Запуск бота...")
        await dp.start_polling(bot)
    except Exception as e:
        logger.critical(f"Критическая ошибка при запуске бота: {str(e)}", exc_info=True)
        raise


# Для Railway важно, чтобы скрипт не завершался при выполнении в контейнере
if __name__ == "__main__":
    try:
        # Railway использует Gunicorn, поэтому скрипт должен запускаться без блокировки основного потока
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Бот остановлен")
    except Exception as e:
        logger.critical(f"Непредвиденная ошибка: {str(e)}", exc_info=True)