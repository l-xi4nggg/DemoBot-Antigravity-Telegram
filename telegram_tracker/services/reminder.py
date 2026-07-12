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
    are 2, 5, or 7 days old. Reminders for each group are consolidated into
    a single Khmer table message, and reminder tracking is updated.
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
        
        from collections import defaultdict
        group_reminders = defaultdict(list)
        
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
                
            # Determine appropriate reminder level based on current age
            target_day = 0
            if age_days >= 7 and last_day < 7:
                target_day = 7
            elif age_days >= 5 and last_day < 5:
                target_day = 5
            elif age_days >= 2 and last_day < 2:
                target_day = 2
                
            if target_day > 0:
                group_reminders[record.group_id].append((record, reminder, target_day))
                
        # Send one consolidated reminder message per group
        for group_id, items in group_reminders.items():
            first_record = items[0][0]
            # Find the manager tag, default to "@manager" if not set
            manager_tag = first_record.group.manager_tag if first_record.group and first_record.group.manager_tag else "@manager"
            
            # Format the Khmer table
            table_lines = [
                "| លេខកូដបេ (Code) | រយៈពេល (Age) | ស្ថានភាព (Status) |",
                "|-----------------|--------------|-------------------|",
            ]
            for record, reminder, target_day in items:
                days_str = f"{target_day} ថ្ងៃ"
                if target_day == 7:
                    status_str = "ការរំលឹកចុងក្រោយ"
                elif target_day == 5:
                    status_str = "មិនទាន់ទទួលបាន"
                else:
                    status_str = "កំពុងរង់ចាំ"
                
                table_lines.append(f"| {record.code:<15} | {days_str:<12} | {status_str:<17} |")
                
            table_content = "\n".join(table_lines)
            message_text = (
                f"🔔 <b>ការរំលឹកតាមដានលេខកូដបេ (Reminder)</b>\n\n"
                f"<pre>\n"
                f"{table_content}\n"
                f"</pre>\n\n"
                f"សូមជួយឆែកនិងតាមឥវ៉ាន់ឱ្យលឿន។\n"
                f"សូមអរគុណ {manager_tag}"
            )
            
            try:
                logger.info(f"Sending consolidated reminder for {len(items)} codes in group {group_id}")
                # Send message via telegram bot
                await bot_app.bot.send_message(
                    chat_id=group_id,
                    text=message_text,
                    parse_mode="HTML"
                )
                
                # Update reminder trackers
                for record, reminder, target_day in items:
                    if not reminder:
                        reminder = Reminder(
                            group_id=record.group_id,
                            code=record.code,
                            last_reminder_day=0
                        )
                        db.add(reminder)
                        db.flush()
                        
                    reminder.last_reminder_day = target_day
                db.commit()
            except Exception as e:
                logger.error(f"Failed to send consolidated reminder for group {group_id}: {e}")
                db.rollback()
