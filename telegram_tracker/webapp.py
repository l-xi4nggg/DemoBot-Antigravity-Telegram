import asyncio
import datetime
import os
from flask import Flask, request

app = Flask(__name__)

init_error = None
bot = None
TELEGRAM_BOT_TOKEN = None

try:
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
    from telegram_tracker.handlers.admin import GUIDE_TEXT
    
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

    # 1. Handle my_chat_member updates (bot added to a group/supergroup)
    my_chat_member = update.get("my_chat_member")
    if my_chat_member:
        chat = my_chat_member.get("chat")
        if chat and chat.get("type") in ["group", "supergroup"]:
            new_chat_member = my_chat_member.get("new_chat_member")
            old_chat_member = my_chat_member.get("old_chat_member")
            if new_chat_member and old_chat_member:
                new_status = new_chat_member.get("status")
                old_status = old_chat_member.get("status")
                active_statuses = ["member", "administrator"]
                is_added = new_status in active_statuses and old_status not in active_statuses
                if is_added:
                    chat_id = chat["id"]
                    run_async(send_message_safely(chat_id, GUIDE_TEXT, parse_mode="Markdown"))
        return "OK", 200

    # Process message (regular or edited)
    message = update.get("message") or update.get("edited_message")
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
            run_async(send_message_safely(chat_id, GUIDE_TEXT, reply_to_message_id=message_id, parse_mode="Markdown"))
            
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
                    run_async(send_message_safely(chat_id, "មិនមានលេខកូដបេដែលមិនទាន់ទទួលបាន ក្នុងគ្រុបនេះទេ។", reply_to_message_id=message_id))
                else:
                    from collections import defaultdict
                    grouped = defaultdict(list)
                    for r in pending_records:
                        date_str = r.send_time.strftime("%Y-%m-%d")
                        sender_name = r.sender.full_name
                        grouped[(date_str, sender_name)].append(r.code)
                        
                    response_parts = [f"📋កំណត់ត្រាលេខកូដបេដែលមិនទាន់ទទួលបាន (ចំនួន {len(pending_records)}កូដ)"]
                    for (date_str, sender_name), codes in grouped.items():
                        block = (
                            f"\n📅កាលបរិច្ឆេទដែលបានកាត់ថ្លៃដើម៖ {date_str} | ផ្ញើដោយ៖ {sender_name}\n\n"
                            f"លេខបេដែលមិនទាន់ទទួលបាន៖\n"
                            + "\n".join(f"• {code}" for code in codes) + "\n\n"
                            f"🔸ស្ថានភាព៖ មិនទាន់ទទួលបាន"
                        )
                        response_parts.append(block)
                    run_async(send_message_safely(chat_id, "\n".join(response_parts), reply_to_message_id=message_id))
                    
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
                    run_async(send_message_safely(chat_id, "មិនមានលេខកូដបេដែលបានទទួល ក្នុងគ្រុបនេះទេ។", reply_to_message_id=message_id))
                else:
                    from collections import defaultdict
                    grouped = defaultdict(list)
                    for r in reversed(completed_records):
                        date_str = r.receive_time.strftime("%Y-%m-%d")
                        receiver_name = r.receiver.full_name if r.receiver else "Unknown"
                        grouped[(date_str, receiver_name)].append(r.code)
                        
                    response_parts = [f"📋កំណត់ត្រាលេខកូដបេដែលបានទទួល (ចំនួន {len(completed_records)}កូដចុងក្រោយ)"]
                    for (date_str, receiver_name), codes in grouped.items():
                        block = (
                            f"\n📅កាលបរិច្ឆេទទទួល៖ {date_str} | ទទួលដោយ៖ {receiver_name}\n\n"
                            f"លេខបេដែលបានទទួល៖\n"
                            + "\n".join(f"• {code}" for code in codes) + "\n\n"
                            f"🔸ស្ថានភាព៖ បានទទួល"
                        )
                        response_parts.append(block)
                    run_async(send_message_safely(chat_id, "\n".join(response_parts), reply_to_message_id=message_id))
                    
        elif cmd == "/find":
            if not args:
                run_async(send_message_safely(chat_id, "Usage: /find <code>", reply_to_message_id=message_id))
                return "OK", 200
                
            from telegram_tracker.services.parser import CODE_PATTERN

            search_text = " ".join(args)
            matches = CODE_PATTERN.finditer(search_text)
            codes = []
            seen = set()
            for match in matches:
                prefix, digits = match.groups()
                normalized_code = f"{prefix.upper()}{digits}"
                if normalized_code not in seen:
                    codes.append(normalized_code)
                    seen.add(normalized_code)

            if not codes:
                run_async(send_message_safely(chat_id, "Usage: /find <code>", reply_to_message_id=message_id))
                return "OK", 200

            now = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)

            with get_db() as db:
                records = (
                    db.query(Record)
                    .filter(Record.group_id == chat_id, Record.code.in_(codes))
                    .all()
                )
                
                db_group = upsert_group(db, chat_id, chat_title)
                manager_tags = db_group.manager_tag if db_group and db_group.manager_tag else ""
                
                record_map = {r.code: r for r in records}
                response_blocks = []
                pending_codes = []
                
                for code in codes:
                    record = record_map.get(code)
                    if not record:
                        block = (
                            f"• {code}\n\n"
                            f"🔸ស្ថានភាព៖ រកមិនឃើញ"
                        )
                    else:
                        send_date = record.send_time.strftime("%Y-%m-%d")
                        if record.status == "SENT":
                            pending_codes.append(code)
                            duration = now - record.send_time
                            pending_days = max(0, duration.days)
                            block = (
                                f"• {record.code}\n\n"
                                f"🔸ស្ថានភាព៖ មិនទាន់បានទទួល\n"
                                f"📅កាលបរិច្ឆេទកាត់ថ្លៃដើម៖ {send_date}\n"
                                f"📅 Pending: {pending_days}ថ្ងៃ"
                            )
                        else:
                            recv_date = record.receive_time.strftime("%Y-%m-%d")
                            block = (
                                f"• {record.code}\n\n"
                                f"🔸ស្ថានភាព៖ បានទទួល\n"
                                f"📅កាលបរិច្ឆេទកាត់ថ្លៃដើម៖ {send_date}\n"
                                f"📅កាលបរិច្ឆេទទទួល៖ {recv_date}"
                            )
                    response_blocks.append(block)
                    
                response_text = "លេខបេ៖\n" + "\n\n".join(response_blocks)
                
                if pending_codes:
                    pending_codes_str = ", ".join(pending_codes)
                    trailer = (
                        f"\n\n------------------------------------\n\n"
                        f"សូមជួយឆែកនិងតាមឥវ៉ាន់លេខបេ {pending_codes_str} មួយនេះបន្តិចផង\n\n"
                        f"អរគុណ {manager_tags}".strip()
                    )
                    response_text += trailer
                    
                run_async(send_message_safely(chat_id, response_text, reply_to_message_id=message_id))
                    
        return "OK", 200

    # 2. Handle group message tracking logic
    parsed = parse_message(text)
    if not parsed:
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
                response_lines.append(f"ស្ថានភាព៖ មិនទាន់បានទទួល")
                response_lines.append(f"អ្នកផ្ញើកូដ៖ {sender_name}")
                response_lines.append(f"កាលបរិច្ឆេទ៖ {now.strftime('%Y-%m-%d')}")
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
                response_lines.append(f"ស្ថានភាព៖ បានទទួល")
                response_lines.append(f"អ្នកទទួលកូដ៖ {receiver_name}")
                response_lines.append(f"កាលបរិច្ឆេទ៖ {now.strftime('%Y-%m-%d')}")
                response = "\n".join(response_lines)

    run_async(send_message_safely(chat_id, response, reply_to_message_id=message_id))
    return "OK", 200

if __name__ == "__main__":
    app.run(port=8080)
