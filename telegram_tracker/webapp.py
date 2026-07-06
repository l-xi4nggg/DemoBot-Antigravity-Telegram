import asyncio
import datetime
import os
from flask import Flask, request
from telegram import Bot
from telegram_tracker.config import TELEGRAM_BOT_TOKEN
from telegram_tracker.database import get_db, init_db
from telegram_tracker.services.parser import parse_message
from telegram_tracker.services.tracker import (
    upsert_user,
    upsert_group,
    record_submission,
    record_receipt,
)
from telegram_tracker.models import Record

app = Flask(__name__)

init_error = None
bot = None
try:
    init_db()
    if not TELEGRAM_BOT_TOKEN:
        raise ValueError("TELEGRAM_BOT_TOKEN environment variable is missing or empty.")
    bot = Bot(token=TELEGRAM_BOT_TOKEN)
except Exception as e:
    import traceback
    init_error = traceback.format_exc()

def run_async(coro):
    """Runs an async coroutine synchronously using a clean event loop."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()

async def send_message_safely(chat_id, text, reply_to_message_id=None, parse_mode=None):
    """Sends a Telegram message, falling back to direct message if reply target is deleted."""
    try:
        if reply_to_message_id:
            await bot.send_message(
                chat_id=chat_id,
                text=text,
                reply_to_message_id=reply_to_message_id,
                parse_mode=parse_mode
            )
        else:
            await bot.send_message(
                chat_id=chat_id,
                text=text,
                parse_mode=parse_mode
            )
    except Exception as e:
        if "Message to be replied not found" in str(e) and reply_to_message_id:
            # Fallback to direct message
            await bot.send_message(
                chat_id=chat_id,
                text=text,
                parse_mode=parse_mode
            )
        else:
            raise

@app.route("/", methods=["GET"])
def index():
    if init_error:
        return f"<h3>Initialization Error:</h3><pre>{init_error}</pre>", 500
    return "Bot is running on Vercel!"

@app.route("/cron/reminders", methods=["GET", "POST"])
def cron_reminders():
    # If CRON_SECRET is configured in environment, verify the Authorization header
    cron_secret = os.environ.get("CRON_SECRET")
    if cron_secret:
        auth_header = request.headers.get("Authorization")
        if not auth_header or auth_header != f"Bearer {cron_secret}":
            return "Unauthorized", 401
            
    from telegram_tracker.services.reminder import check_pending_reminders
    
    class BotAppWrapper:
        def __init__(self, bot_instance):
            self.bot = bot_instance
            
    wrapper = BotAppWrapper(bot)
    try:
        run_async(check_pending_reminders(wrapper))
        return "Reminders checked successfully", 200
    except Exception as e:
        return f"Error running reminders: {str(e)}", 500

@app.route("/webhook", methods=["POST"])
def webhook():
    if init_error:
        return f"Initialization Error:\n{init_error}", 500
    update = request.get_json(force=True)
    if not update:
        return "OK", 200

    # Process message
    message = update.get("message")
    if not message:
        return "OK", 200

    text = message.get("text", "")
    chat = message.get("chat")
    user = message.get("from")
    
    # Only process messages from groups or supergroups
    if not chat or not user or chat.get("type") not in ["group", "supergroup"]:
        return "OK", 200

    chat_id = chat["id"]
    chat_title = chat.get("title", f"Group {chat_id}")
    user_id = user["id"]
    username = user.get("username")
    first_name = user.get("first_name", "")
    last_name = user.get("last_name", "")
    message_id = message["message_id"]

    # 1. Handle command routes
    if text.startswith("/"):
        parts = text.split()
        cmd = parts[0].lower().split("@")[0]
        args = parts[1:]
        
        if cmd == "/guide":
            guide_text = (
                "📖 *Item Packet Tracker Bot Guide*\n\n"
                "Here is how to configure and use the bot in this group:\n\n"
                "1️⃣ *Configure Customer Service*:\n"
                "• `/setservice @username1 [@username2 ...]` - Add customer service members (max 4)\n"
                "• `/replaceservice @old_username @new_username` - Replace a service member\n"
                "• `/resetservice` - Clear all service members\n\n"
                "2️⃣ *Record Sent Packets*:\n"
                "• `[code] cut` / `[code] paid` (or Khmer `កាត់`) - Record code as pending/sent\n"
                "• E.g. `G12345 cut`\n\n"
                "3️⃣ *Receive Packets*:\n"
                "• `[code] received` (or Khmer `ទទួល`) - Mark code as received/collected\n"
                "• E.g. `G12345 received`\n\n"
                "4️⃣ *Queries*:\n"
                "• `/pending` - List all pending packets in this group\n"
                "• `/completed` - List recent completed packets in this group\n"
                "• `/find [code]` - Search packet details\n"
                "• `/guide` - Show this guide again"
            )
            run_async(send_message_safely(chat_id, guide_text, reply_to_message_id=message_id, parse_mode="Markdown"))
            
        elif cmd == "/setservice":
            if not args:
                run_async(send_message_safely(chat_id, "Usage: /setservice @username1 [@username2 ...]", reply_to_message_id=message_id))
                return "OK", 200
                
            new_tags = []
            for arg in args:
                tag = arg.strip()
                if tag:
                    if not tag.startswith("@"):
                        tag = f"@{tag}"
                    new_tags.append(tag)
                    
            with get_db() as db:
                db_group = upsert_group(db, chat_id, chat_title)
                current_tags = db_group.manager_tag.split() if db_group.manager_tag else []
                
                # Add unique tags
                added_tags = []
                for tag in new_tags:
                    if tag not in current_tags:
                        current_tags.append(tag)
                        added_tags.append(tag)
                        
                if len(current_tags) > 4:
                    existing_str = " ".join(db_group.manager_tag.split()) if db_group.manager_tag else "None"
                    run_async(send_message_safely(
                        chat_id, 
                        f"❌ Cannot add. Maximum of 4 customer service members is allowed.\nCurrent members: {existing_str}", 
                        reply_to_message_id=message_id
                    ))
                    return "OK", 200
                    
                db_group.manager_tag = " ".join(current_tags)
                db.commit()
                updated_tags_str = db_group.manager_tag
                
            if added_tags:
                run_async(send_message_safely(chat_id, f"✅ Added customer service member(s): {', '.join(added_tags)}.\nTotal members: {updated_tags_str}", reply_to_message_id=message_id))
            else:
                run_async(send_message_safely(chat_id, f"⚠️ No new members added (already registered).\nTotal members: {updated_tags_str}", reply_to_message_id=message_id))
                
        elif cmd == "/replaceservice":
            if len(args) < 2:
                run_async(send_message_safely(chat_id, "Usage: /replaceservice @old_username @new_username", reply_to_message_id=message_id))
                return "OK", 200
                
            old_tag = args[0].strip()
            if not old_tag.startswith("@"):
                old_tag = f"@{old_tag}"
                
            new_tag = args[1].strip()
            if not new_tag.startswith("@"):
                new_tag = f"@{new_tag}"
                
            with get_db() as db:
                db_group = upsert_group(db, chat_id, chat_title)
                current_tags = db_group.manager_tag.split() if db_group.manager_tag else []
                
                if old_tag not in current_tags:
                    run_async(send_message_safely(chat_id, f"❌ User {old_tag} is not set as a customer service member in this group.", reply_to_message_id=message_id))
                    return "OK", 200
                    
                # Perform replacement
                index = current_tags.index(old_tag)
                if new_tag in current_tags:
                    # If new tag is already present, just remove the old tag to avoid duplicates
                    current_tags.remove(old_tag)
                else:
                    current_tags[index] = new_tag
                    
                db_group.manager_tag = " ".join(current_tags) if current_tags else None
                db.commit()
                updated_tags_str = db_group.manager_tag or "None"
                
            run_async(send_message_safely(chat_id, f"✅ Replaced {old_tag} with {new_tag}.\nTotal members: {updated_tags_str}", reply_to_message_id=message_id))

        elif cmd == "/resetservice":
            with get_db() as db:
                db_group = upsert_group(db, chat_id, chat_title)
                db_group.manager_tag = None
                db.commit()
                
            run_async(send_message_safely(chat_id, "✅ Customer service members reset. No service members are set for this group.", reply_to_message_id=message_id))
            
        elif cmd == "/pending":
            with get_db() as db:
                pending_records = (
                    db.query(Record)
                    .filter(Record.group_id == chat_id, Record.status == "SENT")
                    .order_by(Record.send_time.asc())
                    .all()
                )
                if not pending_records:
                    run_async(send_message_safely(chat_id, "No pending codes found in this group.", reply_to_message_id=message_id))
                else:
                    from collections import defaultdict
                    grouped = defaultdict(list)
                    for r in pending_records:
                        date_str = r.send_time.strftime("%Y-%m-%d")
                        sender_name = r.sender.full_name
                        grouped[(date_str, sender_name)].append(r.code)
                        
                    lines = [f"📋 Pending Codes ({len(pending_records)} items):"]
                    for (date_str, sender_name), codes in grouped.items():
                        lines.append(f"\n📅 {date_str} | Sent by {sender_name}:")
                        for code in codes:
                            lines.append(f"• {code}")
                    run_async(send_message_safely(chat_id, "\n".join(lines), reply_to_message_id=message_id))
                    
        elif cmd == "/completed":
            with get_db() as db:
                completed_records = (
                    db.query(Record)
                    .filter(Record.group_id == chat_id, Record.status == "RECEIVED")
                    .order_by(Record.receive_time.desc())
                    .limit(15)
                    .all()
                )
                if not completed_records:
                    run_async(send_message_safely(chat_id, "No completed codes found in this group.", reply_to_message_id=message_id))
                else:
                    from collections import defaultdict
                    grouped = defaultdict(list)
                    for r in reversed(completed_records):
                        date_str = r.receive_time.strftime("%Y-%m-%d")
                        receiver_name = r.receiver.full_name if r.receiver else "Unknown"
                        grouped[(date_str, receiver_name)].append(r.code)
                        
                    lines = [f"📋 Completed Codes (Last {len(completed_records)} items):"]
                    for (date_str, receiver_name), codes in grouped.items():
                        lines.append(f"\n📅 {date_str} | Received by {receiver_name}:")
                        for code in codes:
                            lines.append(f"• {code}")
                    run_async(send_message_safely(chat_id, "\n".join(lines), reply_to_message_id=message_id))
                    
        elif cmd == "/find":
            if not args:
                run_async(send_message_safely(chat_id, "Usage: /find <code>", reply_to_message_id=message_id))
                return "OK", 200
                
            search_code = args[0].strip().upper()
            with get_db() as db:
                record = db.query(Record).filter(Record.group_id == chat_id, Record.code == search_code).first()
                if not record:
                    run_async(send_message_safely(chat_id, f"❌ Code {search_code} was not found in this group.", reply_to_message_id=message_id))
                else:
                    send_date = record.send_time.strftime("%Y-%m-%d")
                    if record.status == "SENT":
                        response = f"🔍 Found: {record.code} (Pending) | Sender: {record.sender.full_name} | Date Sent: {send_date}"
                    else:
                        recv_date = record.receive_time.strftime("%Y-%m-%d")
                        duration = record.receive_time - record.send_time
                        pending_days = max(0, duration.days)
                        response = f"🔍 Found: {record.code} (Received) | Sender: {record.sender.full_name} | Receiver: {record.receiver.full_name if record.receiver else 'Unknown'} | Pending: {pending_days} Days | Date Sent: {send_date} | Date Received: {recv_date}"
                    run_async(send_message_safely(chat_id, response, reply_to_message_id=message_id))
                    
        return "OK", 200

    # 2. Handle group message tracking logic
    parsed = parse_message(text)
    if not parsed:
        # Check for new member status updates
        new_members = message.get("new_chat_members")
        if new_members:
            for member in new_members:
                # If the bot itself was added to the group
                bot_info = run_async(bot.get_me())
                if member.get("id") == bot_info.id:
                    guide_text = (
                        "📖 *Item Packet Tracker Bot Guide*\n\n"
                        "Here is how to configure and use the bot in this group:\n\n"
                        "1️⃣ *Configure Customer Service*:\n"
                        "• `/setservice @username1 [@username2 ...]` - Add customer service members (max 4)\n"
                        "• `/replaceservice @old_username @new_username` - Replace a service member\n"
                        "• `/resetservice` - Clear all service members\n\n"
                        "2️⃣ *Record Sent Packets*:\n"
                        "• `[code] cut` / `[code] paid` (or Khmer `កាត់`) - Record code as pending/sent\n"
                        "• E.g. `G12345 cut`\n\n"
                        "3️⃣ *Receive Packets*:\n"
                        "• `[code] received` (or Khmer `ទទួល`) - Mark code as received/collected\n"
                        "• E.g. `G12345 received`\n\n"
                        "4️⃣ *Queries*:\n"
                        "• `/pending` - List all pending packets in this group\n"
                        "• `/completed` - List recent completed packets in this group\n"
                        "• `/find [code]` - Search packet details\n"
                        "• `/guide` - Show this guide again"
                    )
                    run_async(send_message_safely(chat_id, guide_text, parse_mode="Markdown"))
                    break
        return "OK", 200

    codes, status = parsed
    
    with get_db() as db:
        upsert_group(db, chat_id, chat_title)
        db_user = upsert_user(db, user_id, username, first_name, last_name)
        now = datetime.datetime.now(datetime.timezone.utc)
        
        if status == "SENT":
            recorded_new = []
            recorded_existing = []
            for code in codes:
                record, is_new = record_submission(db, chat_id, code, user_id, now)
                if is_new:
                    recorded_new.append(record)
                else:
                    recorded_existing.append(record)
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
                response_lines.append(f"Sender: {sender_name}")
                response_lines.append(f"Date: {now.strftime('%Y-%m-%d')}")
                response = "\n".join(response_lines)
                
        elif status == "RECEIVED":
            updated_records = []
            not_found_codes = []
            for code in codes:
                record = record_receipt(db, chat_id, code, user_id, now)
                if record:
                    updated_records.append(record)
                else:
                    not_found_codes.append(code)
            db.commit()
            
            receiver_name = db_user.full_name
            if len(codes) == 1:
                if updated_records:
                    record = updated_records[0]
                    sender_name = record.sender.full_name
                    send_date = record.send_time.strftime("%Y-%m-%d")
                    recv_date = record.receive_time.strftime("%Y-%m-%d")
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
                response_lines.append(f"Receiver: {receiver_name}")
                response_lines.append(f"Date: {now.strftime('%Y-%m-%d')}")
                response = "\n".join(response_lines)

    run_async(send_message_safely(chat_id, response, reply_to_message_id=message_id))
    return "OK", 200

if __name__ == "__main__":
    app.run(port=8080)
