import asyncio
import logging
from telegram import Bot
from telegram_tracker.config import TELEGRAM_BOT_TOKEN
from telegram_tracker.services.reminder import check_pending_reminders

# Configure logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", 
    level=logging.INFO
)
logger = logging.getLogger(__name__)

class BotApp:
    """Mock Bot Application to satisfy the parameter interface of the scheduler."""
    def __init__(self, bot):
        self.bot = bot

async def main():
    logger.info("Starting manual check of pending reminders...")
    bot = Bot(token=TELEGRAM_BOT_TOKEN)
    app = BotApp(bot)
    await check_pending_reminders(app)
    logger.info("Reminder check completed successfully.")

if __name__ == "__main__":
    asyncio.run(main())
