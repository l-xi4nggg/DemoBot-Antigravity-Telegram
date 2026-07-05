import logging
import telegram

logger = logging.getLogger(__name__)

async def reply_safely(message: telegram.Message, text: str, **kwargs) -> telegram.Message:
    """
    Replies to a message. If the message has been deleted or cannot be replied to,
    falls back to sending a direct message to the chat.
    """
    try:
        return await message.reply_text(text, **kwargs)
    except telegram.error.BadRequest as e:
        if "Message to be replied not found" in str(e):
            logger.warning(
                f"Failed to reply to message {message.message_id} (not found/deleted). "
                f"Falling back to direct message in chat {message.chat_id}."
            )
            # Fallback to direct send_message in the same chat
            return await message.get_bot().send_message(
                chat_id=message.chat_id,
                text=text,
                **kwargs
            )
        else:
            raise
