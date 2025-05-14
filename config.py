import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", 0))
ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "")
ADMINS = [int(x) for x in os.getenv("ADMINS", "").split(",") if x.strip()]
CHANNEL_ID = int(os.getenv("CHANNEL_ID", 0))
DATABASE_URL = os.getenv("DATABASE_URL", "")
CHANNEL_URL = os.getenv("CHANNEL_URL", "")

