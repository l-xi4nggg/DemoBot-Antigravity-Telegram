from telegram import Update
from telegram.ext import ContextTypes, CommandHandler
from telegram_tracker.database import get_db
from telegram_tracker.services.tracker import upsert_group
from telegram_tracker.models import Record

async def set_service(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Sets/adds customer service tags for the current group."""
    chat = update.effective_chat
    if not chat or chat.type not in ["group", "supergroup"]:
        await update.message.reply_text("This command can only be used in group chats.")
        return

    # Extract arguments
    if not context.args:
        await update.message.reply_text("Usage: /setservice @username1 [@username2 ...]")
        return

    new_tags = []
    for arg in context.args:
        tag = arg.strip()
        if tag:
            if not tag.startswith("@"):
                tag = f"@{tag}"
            new_tags.append(tag)

    with get_db() as db:
        # Upsert the group first to ensure it exists, then modify manager tag
        db_group = upsert_group(db, chat.id, chat.title or f"Group {chat.id}")
        current_tags = db_group.manager_tag.split() if db_group.manager_tag else []
        
        added_tags = []
        for tag in new_tags:
            if tag not in current_tags:
                current_tags.append(tag)
                added_tags.append(tag)
                
        if len(current_tags) > 4:
            existing_str = " ".join(db_group.manager_tag.split()) if db_group.manager_tag else "None"
            await update.message.reply_text(
                f"❌ Cannot add. Maximum of 4 customer service members is allowed.\nCurrent members: {existing_str}"
            )
            return
            
        db_group.manager_tag = " ".join(current_tags)
        db.commit()
        updated_tags_str = db_group.manager_tag

    if added_tags:
        await update.message.reply_text(
            f"✅ Added customer service member(s): {', '.join(added_tags)}.\nTotal members: {updated_tags_str}"
        )
    else:
        await update.message.reply_text(
            f"⚠️ No new members added (already registered).\nTotal members: {updated_tags_str}"
        )


async def replace_service(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Replaces an existing customer service member with a new one."""
    chat = update.effective_chat
    if not chat or chat.type not in ["group", "supergroup"]:
        await update.message.reply_text("This command can only be used in group chats.")
        return

    if not context.args or len(context.args) < 2:
        await update.message.reply_text("Usage: /replaceservice @old_username @new_username")
        return

    old_tag = context.args[0].strip()
    if not old_tag.startswith("@"):
        old_tag = f"@{old_tag}"

    new_tag = context.args[1].strip()
    if not new_tag.startswith("@"):
        new_tag = f"@{new_tag}"

    with get_db() as db:
        db_group = upsert_group(db, chat.id, chat.title or f"Group {chat.id}")
        current_tags = db_group.manager_tag.split() if db_group.manager_tag else []

        if old_tag not in current_tags:
            await update.message.reply_text(f"❌ User {old_tag} is not set as a customer service member in this group.")
            return

        # Perform replacement
        index = current_tags.index(old_tag)
        if new_tag in current_tags:
            current_tags.remove(old_tag)
        else:
            current_tags[index] = new_tag

        db_group.manager_tag = " ".join(current_tags) if current_tags else None
        db.commit()
        updated_tags_str = db_group.manager_tag or "None"

    await update.message.reply_text(f"✅ Replaced {old_tag} with {new_tag}.\nTotal members: {updated_tags_str}")


async def reset_service(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Clears all customer service members for the group."""
    chat = update.effective_chat
    if not chat or chat.type not in ["group", "supergroup"]:
        await update.message.reply_text("This command can only be used in group chats.")
        return

    with get_db() as db:
        db_group = upsert_group(db, chat.id, chat.title or f"Group {chat.id}")
        db_group.manager_tag = None
        db.commit()

    await update.message.reply_text("✅ Customer service members reset. No service members are set for this group.")

async def list_pending(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Lists all pending codes in the current group."""
    chat = update.effective_chat
    if not chat or chat.type not in ["group", "supergroup"]:
        await reply_safely(update.message, "This command can only be used in group chats.")
        return

    with get_db() as db:
        pending_records = (
            db.query(Record)
            .filter(Record.group_id == chat.id, Record.status == "SENT")
            .order_by(Record.send_time.asc())
            .all()
        )
        
        if not pending_records:
            await reply_safely(update.message, "No pending codes found in this group.")
            return
            
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
            
        await reply_safely(update.message, "\n".join(lines))

async def find_code(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Searches for a specific code in the current group."""
    chat = update.effective_chat
    if not chat or chat.type not in ["group", "supergroup"]:
        await reply_safely(update.message, "This command can only be used in group chats.")
        return

    if not context.args:
        await reply_safely(update.message, "Usage: /find <code>")
        return

    search_code = context.args[0].strip().upper()
    
    with get_db() as db:
        record = (
            db.query(Record)
            .filter(Record.group_id == chat.id, Record.code == search_code)
            .first()
        )
        
        if not record:
            await reply_safely(update.message, f"❌ Code {search_code} was not found in this group.")
            return
            
        send_date = record.send_time.strftime("%Y-%m-%d")
        if record.status == "SENT":
            response = f"🔍 Found: {record.code} (Pending) | Sender: {record.sender.full_name} | Date Sent: {send_date}"
        else:
            recv_date = record.receive_time.strftime("%Y-%m-%d")
            duration = record.receive_time - record.send_time
            pending_days = max(0, duration.days)
            response = f"🔍 Found: {record.code} (Received) | Sender: {record.sender.full_name} | Receiver: {record.receiver.full_name if record.receiver else 'Unknown'} | Pending: {pending_days} Days | Date Sent: {send_date} | Date Received: {recv_date}"
            
        await reply_safely(update.message, response)

async def list_completed(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Lists the most recent completed packet codes in the current group."""
    chat = update.effective_chat
    if not chat or chat.type not in ["group", "supergroup"]:
        await reply_safely(update.message, "This command can only be used in group chats.")
        return

    with get_db() as db:
        completed_records = (
            db.query(Record)
            .filter(Record.group_id == chat.id, Record.status == "RECEIVED")
            .order_by(Record.receive_time.desc())
            .limit(15)
            .all()
        )
        
        if not completed_records:
            await reply_safely(update.message, "No completed codes found in this group.")
            return
            
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
            
        await reply_safely(update.message, "\n".join(lines))

from telegram_tracker.handlers.utils import reply_safely

async def send_guide(message) -> None:
    """Helper to send the bot user guide formatted in Markdown."""
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
    await reply_safely(message, guide_text, parse_mode="Markdown")

async def show_guide(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Sends the user guide to the chat."""
    if update.effective_message:
        await send_guide(update.effective_message)

setservice_handler = CommandHandler("setservice", set_service)
replaceservice_handler = CommandHandler("replaceservice", replace_service)
resetservice_handler = CommandHandler("resetservice", reset_service)
pending_handler = CommandHandler("pending", list_pending)
completed_handler = CommandHandler("completed", list_completed)
find_handler = CommandHandler("find", find_code)
guide_handler = CommandHandler("guide", show_guide)
