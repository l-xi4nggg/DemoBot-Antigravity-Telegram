import datetime
from telegram import Update
from telegram.ext import ContextTypes, MessageHandler, filters, ChatMemberHandler
from telegram_tracker.database import get_db
from telegram_tracker.services.parser import parse_message
from telegram_tracker.services.tracker import (
    upsert_user,
    upsert_group,
    record_submission,
    record_receipt,
)

from telegram_tracker.handlers.utils import reply_safely

async def handle_group_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles messages in group chats, parses for codes and updates the database."""
    message = update.effective_message
    if not message or not message.text:
        return
        
    chat = update.effective_chat
    # Only process messages from groups or supergroups
    if not chat or chat.type not in ["group", "supergroup"]:
        return
        
    user = update.effective_user
    if not user:
        return

    # Parse message for codes and status
    parsed = parse_message(message.text)
    if not parsed:
        return
        
    codes, status = parsed
    
    # Process database operations
    with get_db() as db:
        # Register/update the Group and User details
        upsert_group(db, chat.id, chat.title or f"Group {chat.id}")
        db_user = upsert_user(
            db, 
            user.id, 
            user.username, 
            user.first_name, 
            user.last_name
        )
        
        now = datetime.datetime.now(datetime.timezone.utc)
        
        if status == "SENT":
            recorded_new = []
            recorded_existing = []
            
            for code in codes:
                record, is_new = record_submission(db, chat.id, code, user.id, now)
                if is_new:
                    recorded_new.append(record)
                else:
                    recorded_existing.append(record)
            
            # Commit session changes
            db.commit()
            
            sender_name = db_user.full_name
            
            if len(codes) == 1:
                record = recorded_new[0] if recorded_new else recorded_existing[0]
                date_str = record.send_time.strftime("%Y-%m-%d")
                
                if recorded_new:
                    response = (
                        f"កត់ត្រាកូដដែលបានកាត់ថ្លៃដើម (ចំនួន 1កូដថ្មី)\n\n"
                        f"លេខបេ៖ {record.code}\n\n"
                        f"ស្ថានភាព៖ មិនទាន់បានទទួល\n"
                        f"អ្នកផ្ញើកូដ៖ {sender_name}\n"
                        f"កាលបរិច្ឆេទ៖ {date_str}"
                    )
                else:
                    status_display = "មិនទាន់បានទទួល" if record.status == "SENT" else "បានទទួល"
                    response = (
                        f"⚠️ កូដនេះត្រូវបានកត់ត្រារួចហើយ\n\n"
                        f"លេខបេ៖ {record.code}\n\n"
                        f"ស្ថានភាព៖ {status_display}\n"
                        f"អ្នកផ្ញើកូដ៖ {record.sender.full_name}\n"
                        f"កាលបរិច្ឆេទ៖ {record.send_time.strftime('%Y-%m-%d')}"
                    )
            else:
                summary_parts = []
                if recorded_new:
                    summary_parts.append(f"{len(recorded_new)}កូដថ្មី")
                if recorded_existing:
                    summary_parts.append(f"{len(recorded_existing)}កូដមានរួច")
                summary_str = ", ".join(summary_parts)
                
                response_lines = [f"កត់ត្រាកូដដែលបានកាត់ថ្លៃដើម (ចំនួន {summary_str})\n"]
                
                if recorded_new:
                    if recorded_existing:
                        response_lines.append("លេខបេថ្មី៖")
                    else:
                        response_lines.append("លេខបេ៖")
                    for r in recorded_new:
                        response_lines.append(f"• {r.code}")
                    response_lines.append("")
                    
                if recorded_existing:
                    response_lines.append("លេខបេមានរួច៖")
                    for r in recorded_existing:
                        response_lines.append(f"• {r.code}")
                    response_lines.append("")
                    
                date_str = now.strftime("%Y-%m-%d")
                response_lines.append(f"ស្ថានភាព៖ មិនទាន់បានទទួល")
                response_lines.append(f"អ្នកផ្ញើកូដ៖ {sender_name}")
                response_lines.append(f"កាលបរិច្ឆេទ៖ {date_str}")
                response = "\n".join(response_lines)
                
        elif status == "RECEIVED":
            updated_records = []
            not_found_codes = []
            
            for code in codes:
                record = record_receipt(db, chat.id, code, user.id, now)
                if record:
                    updated_records.append(record)
                else:
                    not_found_codes.append(code)
            
            if updated_records or not_found_codes:
                db.commit()
                
            receiver_name = db_user.full_name
            
            if len(codes) == 1:
                if updated_records:
                    record = updated_records[0]
                    sender_name = record.sender.full_name
                    send_date = record.send_time.strftime("%Y-%m-%d")
                    recv_date = record.receive_time.strftime("%Y-%m-%d")
                    
                    # Calculate pending duration in days
                    send_time_naive = record.send_time.replace(tzinfo=None) if record.send_time.tzinfo else record.send_time
                    recv_time_naive = record.receive_time.replace(tzinfo=None) if record.receive_time.tzinfo else record.receive_time
                    duration = recv_time_naive - send_time_naive
                    pending_days = max(0, duration.days)
                    
                    response = (
                        f"✅ បានទទួលកូដរួចរាល់ (ចំនួន 1កូដ)\n\n"
                        f"លេខបេ៖ {record.code}\n\n"
                        f"ស្ថានភាព៖ បានទទួល\n"
                        f"អ្នកផ្ញើកូដ៖ {sender_name}\n"
                        f"អ្នកទទួលកូដ៖ {receiver_name}\n"
                        f"កាលបរិច្ឆេទផ្ញើ៖ {send_date}\n"
                        f"កាលបរិច្ឆេទទទួល៖ {recv_date}\n"
                        f"រយៈពេលរង់ចាំ៖ {pending_days} ថ្ងៃ\n"
                        f"កាលបរិច្ឆេទកែប្រែ៖ {recv_date}"
                    )
                else:
                    response = (
                        f"❌ រកមិនឃើញកូដ\n\n"
                        f"កូដ {codes[0]} មិនត្រូវបានរកឃើញ ឬកត់ត្រាក្នុងគ្រុបនេះទេ។"
                    )
            else:
                summary_parts = []
                if updated_records:
                    summary_parts.append(f"{len(updated_records)}កូដបានទទួល")
                if not_found_codes:
                    summary_parts.append(f"{len(not_found_codes)}កូដរកមិនឃើញ")
                summary_str = ", ".join(summary_parts)
                
                response_lines = [f"✅ ទទួលកូដរួចរាល់ (ចំនួន {summary_str})\n"]
                
                if updated_records:
                    response_lines.append("លេខបេបានទទួល៖")
                    for r in updated_records:
                        response_lines.append(f"• {r.code}")
                    response_lines.append("")
                    
                if not_found_codes:
                    response_lines.append("លេខបេរកមិនឃើញ៖")
                    for c in not_found_codes:
                        response_lines.append(f"• {c}")
                    response_lines.append("")
                    
                recv_date = now.strftime("%Y-%m-%d")
                response_lines.append(f"ស្ថានភាព៖ បានទទួល")
                response_lines.append(f"អ្នកទទួលកូដ៖ {receiver_name}")
                response_lines.append(f"កាលបរិច្ឆេទ៖ {recv_date}")
                response = "\n".join(response_lines)
                
    await reply_safely(message, response)

# Export the message handler registration
group_message_handler = MessageHandler(
    filters.TEXT & (~filters.COMMAND), 
    handle_group_message
)



async def handle_my_chat_member(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Sends the guide automatically when the bot is added to a new group/supergroup."""
    my_chat_member = update.my_chat_member
    if not my_chat_member:
        return
        
    chat = my_chat_member.chat
    if not chat or chat.type not in ["group", "supergroup"]:
        return
        
    old_status = my_chat_member.old_chat_member.status
    new_status = my_chat_member.new_chat_member.status
    
    # We want to trigger when the bot is added as a member or administrator
    # and it was not previously a member or administrator.
    active_statuses = ["member", "administrator"]
    if new_status in active_statuses and old_status not in active_statuses:
        from telegram_tracker.handlers.admin import GUIDE_TEXT
        await context.bot.send_message(
            chat_id=chat.id,
            text=GUIDE_TEXT,
            parse_mode="Markdown"
        )

my_chat_member_handler = ChatMemberHandler(
    handle_my_chat_member,
    chat_member_types=ChatMemberHandler.MY_CHAT_MEMBER
)
