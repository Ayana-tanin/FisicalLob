import os
import logging
from dotenv import load_dotenv

load_dotenv()

# Настройка логирования для отладки проблем с переменными окружения
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", 0))
ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "")
ADMINS = [int(x) for x in os.getenv("ADMINS", "").split(",") if x.strip()]
CHANNEL_ID = int(os.getenv("CHANNEL_ID", 0))
CHANNEL_URL = os.getenv("CHANNEL_URL", "")

# Приоритетно используем DATABASE_URL (стандартная для Railway)
DATABASE_URL = os.getenv("DATABASE_URL")

# Если DATABASE_URL не установлен, логируем ошибку
if not DATABASE_URL:
    logger.error("DATABASE_URL не найден в переменных окружения!")
else:
    # Логируем первые несколько символов для отладки (без паролей)
    masked_url = DATABASE_URL.split("@")[0][:10] + "..." if "@" in DATABASE_URL else DATABASE_URL[:10] + "..."
    logger.info(f"DATABASE_URL обнаружен: {masked_url}")