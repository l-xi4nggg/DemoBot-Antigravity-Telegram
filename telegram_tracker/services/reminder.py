import datetime
import logging
from sqlalchemy.orm import joinedload
from telegram_tracker.database import get_db
from telegram_tracker.models.record import Record
from telegram_tracker.models.reminder import Reminder

logger = logging.getLogger(__name__)

async def check_pending_reminders(bot_app) -> None:
    """
    Checks all pending records (status = SENT) and sends reminders if they
    are 2, 5, or 7 days old, and updates the reminder tracking.
    """
    logger.info("Running pending reminders check...")
    now = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)
    
    with get_db() as db:
        # Fetch all records that are still in "SENT" status, pre-fetching group info
        pending_records = (
            db.query(Record)
            .options(joinedload(Record.group))
            .filter(Record.status == "SENT")
            .all()
        )
        
        for record in pending_records:
            # Calculate age in days
            send_time_naive = record.send_time.replace(tzinfo=None) if record.send_time.tzinfo else record.send_time
            age_timedelta = now - send_time_naive
            age_days = age_timedelta.days
            
            # Fetch the reminder track record (if it exists)
            reminder = db.query(Reminder).filter(
                Reminder.group_id == record.group_id,
                Reminder.code == record.code
            ).first()
            
            last_day = reminder.last_reminder_day if reminder else 0
                
            # Check what level of reminder we need to send
            target_day = 0
            message_text = ""
            
            # Find the manager tag, default to "@manager" if not set
            manager_tag = record.group.manager_tag if record.group.manager_tag else "@manager"
            
            # Determine appropriate reminder level based on current age
            if age_days >= 7 and last_day < 7:
                target_day = 7
                message_text = (
                    f"Reminder\n\n"
                    f"7 days\n\n"
                    f"Final reminder\n\n"
                    f"{manager_tag}"
                )
            elif age_days >= 5 and last_day < 5:
                target_day = 5
                message_text = (
                    f"Reminder\n\n"
                    f"Pending\n\n"
                    f"5 days\n\n"
                    f"{manager_tag}"
                )
            elif age_days >= 2 and last_day < 2:
                target_day = 2
                message_text = (
                    f"Reminder\n\n"
                    f"Pending Code\n\n"
                    f"{record.code}\n\n"
                    f"Waiting\n\n"
                    f"2 days\n\n"
                    f"{manager_tag}"
                )
                
            if target_day > 0 and message_text:
                try:
                    logger.info(f"Sending Day {target_day} reminder for code {record.code} in group {record.group_id}")
                    # Send message via telegram bot
                    await bot_app.bot.send_message(
                        chat_id=record.group_id,
                        text=message_text
                    )
                    
                    # Create the reminder tracker record if it didn't exist
                    if not reminder:
                        reminder = Reminder(
                            group_id=record.group_id,
                            code=record.code,
                            last_reminder_day=0
                        )
                        db.add(reminder)
                        db.flush()
                        
                    # Update reminder record
                    reminder.last_reminder_day = target_day
                    db.commit()
                except Exception as e:
                    logger.error(f"Failed to send reminder for code {record.code}: {e}")
                    db.rollback()
