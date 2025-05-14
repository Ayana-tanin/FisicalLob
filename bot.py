import asyncio
import logging
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from config import BOT_TOKEN
from db_connection import init_db
from handlers import router

# Настройка логирования с более подробной информацией
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


async def main():
    """
    Основная функция, инициализирует бота и запускает его.
    """
    try:
        # Инициализация базы данных
        logger.info("Инициализация базы данных...")
        init_db()

        # Создание экземпляра бота
        logger.info("Создание экземпляра бота...")
        bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))

        # Создание диспетчера
        dp = Dispatcher(storage=MemoryStorage())
        dp.include_router(router)

        # Запуск бота
        logger.info("Запуск бота...")
        await dp.start_polling(bot)
    except Exception as e:
        logger.critical(f"Критическая ошибка при запуске бота: {str(e)}", exc_info=True)
        raise


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Бот остановлен")
    except Exception as e:
        logger.critical(f"Непредвиденная ошибка: {str(e)}", exc_info=True)