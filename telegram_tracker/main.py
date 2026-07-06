import sys
from pathlib import Path

# Add project root to sys.path to resolve local package imports
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import logging
from telegram.ext import Application
from telegram_tracker.config import TELEGRAM_BOT_TOKEN
from telegram_tracker.database import init_db
from telegram_tracker.handlers import (
    group_message_handler,
    new_member_handler,
    setservice_handler,
    replaceservice_handler,
    resetservice_handler,
    pending_handler,
    completed_handler,
    find_handler,
    guide_handler,
)
from telegram_tracker.scheduler import setup_scheduler

# Configure logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", 
    level=logging.INFO
)
logger = logging.getLogger(__name__)

async def post_init(application: Application) -> None:
    """Callback after the application has initialized and event loop is running."""
    logger.info("Starting background scheduler...")
    scheduler = setup_scheduler(application)
    application.bot_data["scheduler"] = scheduler
    
    # Register bot commands for autocompletion in Telegram
    from telegram import BotCommand
    commands = [
        BotCommand("guide", "Show the bot guide"),
        BotCommand("setservice", "Add customer service members"),
        BotCommand("replaceservice", "Replace a service member"),
        BotCommand("resetservice", "Clear all service members"),
        BotCommand("pending", "List all pending codes"),
        BotCommand("completed", "List recent completed codes"),
        BotCommand("find", "Search details of a specific code"),
    ]
    await application.bot.set_my_commands(commands)
    logger.info("Bot commands menu registered successfully.")

async def post_shutdown(application: Application) -> None:
    """Callback after the application has shut down. Clean up resources here."""
    logger.info("Stopping background scheduler...")
    scheduler = application.bot_data.get("scheduler")
    if scheduler:
        scheduler.shutdown()
        logger.info("Scheduler stopped successfully.")

def main() -> None:
    # 1. Initialize Database Tables
    logger.info("Initializing database...")
    init_db()
    logger.info("Database initialized successfully.")

    # 2. Check for Bot Token
    if not TELEGRAM_BOT_TOKEN or TELEGRAM_BOT_TOKEN == "your_telegram_bot_token_here":
        logger.error(
            "TELEGRAM_BOT_TOKEN is not configured! "
            "Please copy .env.example to .env and configure your bot token from @BotFather."
        )
        sys.exit(1)

    # 3. Create Application
    logger.info("Building Telegram Application...")
    application = (
        Application.builder()
        .token(TELEGRAM_BOT_TOKEN)
        .post_init(post_init)
        .post_shutdown(post_shutdown)
        .build()
    )

    # 4. Register Handlers (Commands must be added before general message handlers)
    application.add_handler(guide_handler)
    application.add_handler(setservice_handler)
    application.add_handler(replaceservice_handler)
    application.add_handler(resetservice_handler)
    application.add_handler(pending_handler)
    application.add_handler(completed_handler)
    application.add_handler(find_handler)
    application.add_handler(new_member_handler)
    application.add_handler(group_message_handler)

    # 5. Start Polling
    logger.info("Starting bot polling. Press Ctrl+C to stop.")
    application.run_polling()

if __name__ == "__main__":
    main()
