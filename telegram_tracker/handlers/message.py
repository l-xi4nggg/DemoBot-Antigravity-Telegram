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
                        f"✅ Recorded\n\n"
                        f"Code: {record.code}\n\n"
                        f"Status: Pending\n\n"
                        f"Sender: {sender_name}\n\n"
                        f"Date: {date_str}"
                    )
                else:
                    status_display = "Pending" if record.status == "SENT" else "Received"
                    response = (
                        f"⚠️ Code Already Recorded\n\n"
                        f"Code: {record.code}\n\n"
                        f"Status: {status_display}\n\n"
                        f"Sender: {record.sender.full_name}\n\n"
                        f"Date: {record.send_time.strftime('%Y-%m-%d')}"
                    )
            else:
                summary_parts = []
                if recorded_new:
                    summary_parts.append(f"{len(recorded_new)} new")
                if recorded_existing:
                    summary_parts.append(f"{len(recorded_existing)} already registered")
                summary_str = ", ".join(summary_parts)
                
                response_lines = [f"✅ Recorded ({summary_str})\n"]
                
                if recorded_new:
                    response_lines.append("New Codes:")
                    for r in recorded_new:
                        response_lines.append(f"• {r.code} (Pending)")
                    response_lines.append("")
                    
                if recorded_existing:
                    response_lines.append("Already Recorded:")
                    for r in recorded_existing:
                        status_display = "Pending" if r.status == "SENT" else "Received"
                        response_lines.append(f"• {r.code} ({status_display})")
                    response_lines.append("")
                    
                date_str = now.strftime("%Y-%m-%d")
                response_lines.append(f"Sender: {sender_name}")
                response_lines.append(f"Date: {date_str}")
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
                    duration = record.receive_time - record.send_time
                    pending_days = max(0, duration.days)
                    
                    response = (
                        f"✅ Updated\n\n"
                        f"Code: {record.code}\n\n"
                        f"Status: Received\n\n"
                        f"Sender: {sender_name}\n\n"
                        f"Receiver: {receiver_name}\n\n"
                        f"Date Sent: {send_date}\n\n"
                        f"Date Received: {recv_date}\n\n"
                        f"Pending Duration: {pending_days} Days\n\n"
                        f"Updated: {recv_date}"
                    )
                else:
                    response = (
                        f"❌ Code Not Found\n\n"
                        f"Code {codes[0]} was not found/registered in this group."
                    )
            else:
                summary_parts = []
                if updated_records:
                    summary_parts.append(f"{len(updated_records)} completed")
                if not_found_codes:
                    summary_parts.append(f"{len(not_found_codes)} not found")
                summary_str = ", ".join(summary_parts)
                
                response_lines = [f"✅ Completed ({summary_str})\n"]
                
                if updated_records:
                    response_lines.append("Completed Codes:")
                    for r in updated_records:
                        response_lines.append(f"• {r.code} (Received)")
                    response_lines.append("")
                    
                if not_found_codes:
                    response_lines.append("Not Found Codes:")
                    for c in not_found_codes:
                        response_lines.append(f"• {c}")
                    response_lines.append("")
                    
                recv_date = now.strftime("%Y-%m-%d")
                response_lines.append(f"Receiver: {receiver_name}")
                response_lines.append(f"Date: {recv_date}")
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
