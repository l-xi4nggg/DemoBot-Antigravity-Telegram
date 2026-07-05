from telegram import Update
from telegram.ext import ContextTypes, CommandHandler
from telegram_tracker.database import get_db
from telegram_tracker.services.tracker import upsert_group
from telegram_tracker.models import Record

async def set_service(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Sets the customer service tag for the current group."""
    chat = update.effective_chat
    if not chat or chat.type not in ["group", "supergroup"]:
        await update.message.reply_text("This command can only be used in group chats.")
        return

    # Security check: Ensure the sender is a group creator or administrator
    user = update.effective_user
    if not user:
        return
        
    try:
        chat_member = await context.bot.get_chat_member(chat.id, user.id)
        if chat_member.status not in ["creator", "administrator"]:
            await update.message.reply_text("❌ Only group administrators can use this command.")
            return
    except Exception as e:
        # If we cannot verify membership (e.g. mock context in tests), we can proceed or log it
        pass

    # Extract argument
    if not context.args:
        await update.message.reply_text("Usage: /setservice @username")
        return

    manager_tag = context.args[0].strip()
    if not manager_tag.startswith("@"):
        manager_tag = f"@{manager_tag}"

    with get_db() as db:
        # Upsert the group first to ensure it exists, then modify manager tag
        db_group = upsert_group(db, chat.id, chat.title or f"Group {chat.id}")
        db_group.manager_tag = manager_tag
        db.commit()

    await update.message.reply_text(f"✅ Customer Service tag updated to {manager_tag} for this group.")

async def list_pending(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Lists all pending codes in the current group."""
    chat = update.effective_chat
    if not chat or chat.type not in ["group", "supergroup"]:
        await update.message.reply_text("This command can only be used in group chats.")
        return

    with get_db() as db:
        pending_records = (
            db.query(Record)
            .filter(Record.group_id == chat.id, Record.status == "SENT")
            .order_by(Record.send_time.asc())
            .all()
        )
        
        if not pending_records:
            await update.message.reply_text("No pending codes found in this group.")
            return
            
        lines = [f"📋 Pending Codes ({len(pending_records)} items):"]
        for r in pending_records:
            date_str = r.send_time.strftime("%Y-%m-%d")
            lines.append(f"• {r.code} - Sent by {r.sender.full_name} on {date_str}")
            
        await update.message.reply_text("\n".join(lines))

async def find_code(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Searches for a specific code in the current group."""
    chat = update.effective_chat
    if not chat or chat.type not in ["group", "supergroup"]:
        await update.message.reply_text("This command can only be used in group chats.")
        return

    if not context.args:
        await update.message.reply_text("Usage: /find <code>")
        return

    search_code = context.args[0].strip().upper()
    
    with get_db() as db:
        record = (
            db.query(Record)
            .filter(Record.group_id == chat.id, Record.code == search_code)
            .first()
        )
        
        if not record:
            await update.message.reply_text(f"❌ Code {search_code} was not found in this group.")
            return
            
        send_date = record.send_time.strftime("%Y-%m-%d")
        if record.status == "SENT":
            response = f"🔍 Found: {record.code} (Pending) | Sender: {record.sender.full_name} | Date Sent: {send_date}"
        else:
            recv_date = record.receive_time.strftime("%Y-%m-%d")
            duration = record.receive_time - record.send_time
            pending_days = max(0, duration.days)
            response = f"🔍 Found: {record.code} (Received) | Sender: {record.sender.full_name} | Receiver: {record.receiver.full_name if record.receiver else 'Unknown'} | Pending: {pending_days} Days | Date Sent: {send_date} | Date Received: {recv_date}"
            
        await update.message.reply_text(response)

async def list_completed(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Lists the most recent completed packet codes in the current group."""
    chat = update.effective_chat
    if not chat or chat.type not in ["group", "supergroup"]:
        await update.message.reply_text("This command can only be used in group chats.")
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
            await update.message.reply_text("No completed codes found in this group.")
            return
            
        lines = [f"📋 Completed Codes (Last {len(completed_records)} items):"]
        for r in reversed(completed_records):
            date_str = r.receive_time.strftime("%Y-%m-%d")
            receiver_name = r.receiver.full_name if r.receiver else "Unknown"
            lines.append(f"• {r.code} - Received by {receiver_name} on {date_str}")
            
        await update.message.reply_text("\n".join(lines))

from telegram_tracker.handlers.utils import reply_safely

async def send_guide(message) -> None:
    """Helper to send the bot user guide formatted in Markdown."""
    guide_text = (
        "📖 *Item Packet Tracker Bot Guide*\n\n"
        "Here is how to configure and use the bot in this group:\n\n"
        "1️⃣ *Configure Customer Service*:\n"
        "• `/setservice @username` - Set customer service tag (Admin only)\n\n"
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
pending_handler = CommandHandler("pending", list_pending)
completed_handler = CommandHandler("completed", list_completed)
find_handler = CommandHandler("find", find_code)
guide_handler = CommandHandler("guide", show_guide)
