import sys
from pathlib import Path

# Add project root to sys.path to resolve local package imports
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import datetime
import unittest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# Set database URL to a local file for testing BEFORE importing database module
import os
os.environ["DATABASE_URL"] = "sqlite:///test_tracker.db"

from telegram_tracker.database import Base
from telegram_tracker.services.parser import parse_message
from telegram_tracker.services.tracker import (
    upsert_user,
    upsert_group,
    record_submission,
    record_receipt,
)
from telegram_tracker.models.record import Record
from telegram_tracker.models.user import User
from telegram_tracker.models.group import Group

class TestParser(unittest.TestCase):
    def test_parse_sent_english(self):
        self.assertEqual(parse_message("G123456 cut"), (["G123456"], "SENT"))
        self.assertEqual(parse_message("TB98213 paid"), (["TB98213"], "SENT"))
        self.assertEqual(parse_message("F8888 paid"), (["F8888"], "SENT"))
        self.assertEqual(parse_message("Y999 cut"), (["Y999"], "SENT"))

    def test_parse_sent_khmer(self):
        self.assertEqual(parse_message("Y100001 កាត់"), (["Y100001"], "SENT"))
        self.assertEqual(parse_message("បានកាត់ G12345"), (["G12345"], "SENT"))
        self.assertEqual(parse_message("G12345 កាត់រួចរាល់"), (["G12345"], "SENT"))
        self.assertEqual(parse_message("G12345 កាត់រួច"), (["G12345"], "SENT"))
        self.assertEqual(parse_message("G12345 រួចរាល់"), (["G12345"], "SENT"))

    def test_parse_received_english(self):
        self.assertEqual(parse_message("G123456 received"), (["G123456"], "RECEIVED"))
        self.assertEqual(parse_message("TB98213 receive"), (["TB98213"], "RECEIVED"))

    def test_parse_received_khmer(self):
        self.assertEqual(parse_message("បានទទួល G123456"), (["G123456"], "RECEIVED"))
        self.assertEqual(parse_message("G123456 ទទួល"), (["G123456"], "RECEIVED"))
        self.assertEqual(parse_message("G123456 បានទទួលរួច"), (["G123456"], "RECEIVED"))
        self.assertEqual(parse_message("G123456 បាន"), (["G123456"], "RECEIVED"))

    def test_parse_multiple_codes(self):
        self.assertEqual(
            parse_message("G123456 F2222 TB3333 Y4444 cut"), 
            (["G123456", "F2222", "TB3333", "Y4444"], "SENT")
        )
        self.assertEqual(
            parse_message("G123 G123 F456 received"), 
            (["G123", "F456"], "RECEIVED")  # Deduplicated
        )

    def test_invalid_codes(self):
        # Invalid prefix or format
        self.assertIsNone(parse_message("GG123 cut"))
        self.assertIsNone(parse_message("ABC111 cut"))
        self.assertIsNone(parse_message("TG123 cut"))
        # Words touching codes without boundary
        self.assertIsNone(parse_message("abcG123 cut"))
        self.assertIsNone(parse_message("G123abc cut"))

    def test_ambiguous_keywords(self):
        # Both keywords present should return None
        self.assertIsNone(parse_message("G12345 cut received"))
        self.assertIsNone(parse_message("G12345 បានកាត់ បានទទួល"))

    def test_no_keywords(self):
        # Missing keyword
        self.assertIsNone(parse_message("G12345"))


class TestTrackerService(unittest.TestCase):
    def setUp(self):
        from telegram_tracker.database import init_db, SessionLocal
        init_db()
        self.db = SessionLocal()

    def tearDown(self):
        self.db.close()
        from telegram_tracker.database import Base, engine
        Base.metadata.drop_all(bind=engine)
        engine.dispose()

    def test_upsert_user(self):
        # 1. New user creation
        user = upsert_user(self.db, 111, "alice", "Alice", "Smith")
        self.db.commit()
        
        self.assertEqual(user.id, 111)
        self.assertEqual(user.username, "alice")
        self.assertEqual(user.first_name, "Alice")
        self.assertEqual(user.last_name, "Smith")
        self.assertEqual(user.full_name, "Alice Smith")
        self.assertEqual(user.display_name, "@alice")

        # 2. Update existing user
        updated_user = upsert_user(self.db, 111, None, "Alice", "Updated")
        self.db.commit()
        self.assertEqual(updated_user.id, 111)
        self.assertEqual(updated_user.username, None)
        self.assertEqual(updated_user.last_name, "Updated")
        self.assertEqual(updated_user.display_name, "Alice Updated")

    def test_upsert_group(self):
        # 1. New group
        group = upsert_group(self.db, -1001, "Test Group")
        self.db.commit()
        self.assertEqual(group.id, -1001)
        self.assertEqual(group.title, "Test Group")

        # 2. Update existing group title
        updated_group = upsert_group(self.db, -1001, "New Title")
        self.db.commit()
        self.assertEqual(updated_group.title, "New Title")

    def test_tracker_flow(self):
        # Setup pre-requisite entities
        upsert_group(self.db, -1001, "Test Group")
        upsert_user(self.db, 101, "sender_user", "Sender", "Bob")
        upsert_user(self.db, 202, "receiver_user", "Receiver", "Charlie")
        self.db.commit()

        send_time = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)
        receive_time = send_time + datetime.timedelta(hours=2)

        # 1. Submit a pending code
        record, is_new = record_submission(self.db, -1001, "G9999", 101, send_time)
        self.db.commit()
        
        self.assertTrue(is_new)
        self.assertEqual(record.code, "G9999")
        self.assertEqual(record.status, "SENT")
        self.assertEqual(record.sender_id, 101)
        self.assertIsNone(record.receiver_id)
        self.assertEqual(record.send_time, send_time)

        # 2. Re-submitting the same code should return is_new = False
        record2, is_new2 = record_submission(self.db, -1001, "G9999", 101, send_time)
        self.db.commit()
        self.assertFalse(is_new2)
        self.assertEqual(record2.code, "G9999")

        # 3. Receive the code
        record_recv = record_receipt(self.db, -1001, "G9999", 202, receive_time)
        self.db.commit()
        
        self.assertIsNotNone(record_recv)
        self.assertEqual(record_recv.status, "RECEIVED")
        self.assertEqual(record_recv.receiver_id, 202)
        self.assertEqual(record_recv.receive_time, receive_time)

        # 4. Attempt to receive a non-existent code
        record_not_found = record_receipt(self.db, -1001, "F1111", 202, receive_time)
        self.assertIsNone(record_not_found)


from unittest.mock import AsyncMock, MagicMock
from telegram_tracker.models.reminder import Reminder
from telegram_tracker.services.reminder import check_pending_reminders

class TestPhase2Reminders(unittest.TestCase):
    def setUp(self):
        from telegram_tracker.database import init_db, SessionLocal
        init_db()
        self.db = SessionLocal()

    def tearDown(self):
        self.db.close()
        from telegram_tracker.database import Base, engine
        Base.metadata.drop_all(bind=engine)
        engine.dispose()

    async def async_test_reminders_logic(self):
        # Setup group, manager and records
        upsert_group(self.db, -1002, "Group 2")
        # Update group manager tag
        group = self.db.query(Group).filter(Group.id == -1002).first()
        group.manager_tag = "@alice_manager"
        
        upsert_user(self.db, 303, "sender3", "Sender", "Three")
        self.db.commit()

        now = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)
        
        # 1. Record sent 1 day ago (should trigger NO reminder)
        time_1_day_ago = now - datetime.timedelta(days=1)
        record_submission(self.db, -1002, "G111", 303, time_1_day_ago)
        
        # 2. Record sent 3 days ago (should trigger Day 2 reminder)
        time_3_days_ago = now - datetime.timedelta(days=3)
        record_submission(self.db, -1002, "G222", 303, time_3_days_ago)

        # 3. Record sent 6 days ago (should trigger Day 5 reminder)
        time_6_days_ago = now - datetime.timedelta(days=6)
        record_submission(self.db, -1002, "G555", 303, time_6_days_ago)

        # 4. Record sent 8 days ago (should trigger Day 7 final reminder)
        time_8_days_ago = now - datetime.timedelta(days=8)
        record_submission(self.db, -1002, "G777", 303, time_8_days_ago)

        self.db.commit()

        # Mock Bot Application
        mock_bot_app = MagicMock()
        mock_bot_app.bot.send_message = AsyncMock()

        # Run checks
        await check_pending_reminders(mock_bot_app)

        # Check mock calls
        # We expect 1 consolidated send_message call (containing G222, G555, G777)
        self.assertEqual(mock_bot_app.bot.send_message.call_count, 1)
        
        # Verify content
        sent_text = mock_bot_app.bot.send_message.call_args[1]["text"]
        self.assertIn("G222", sent_text)
        self.assertIn("G555", sent_text)
        self.assertIn("G777", sent_text)
        self.assertIn("កំពុងរង់ចាំ", sent_text)
        self.assertIn("មិនទាន់ទទួលបាន", sent_text)
        self.assertIn("ការរំលឹកចុងក្រោយ", sent_text)

        # Verify reminders in DB
        r_g111 = self.db.query(Reminder).filter(Reminder.code == "G111").first()
        r_g222 = self.db.query(Reminder).filter(Reminder.code == "G222").first()
        r_g555 = self.db.query(Reminder).filter(Reminder.code == "G555").first()
        r_g777 = self.db.query(Reminder).filter(Reminder.code == "G777").first()

        # G111 had no reminder record created because age was < 2 days
        self.assertIsNone(r_g111)
        
        self.assertIsNotNone(r_g222)
        self.assertEqual(r_g222.last_reminder_day, 2)

        self.assertIsNotNone(r_g555)
        self.assertEqual(r_g555.last_reminder_day, 5)

        self.assertIsNotNone(r_g777)
        self.assertEqual(r_g777.last_reminder_day, 7)

        # 5. Run check again. It should NOT send new messages because reminder state matches age.
        mock_bot_app.bot.send_message.reset_mock()
        await check_pending_reminders(mock_bot_app)
        mock_bot_app.bot.send_message.assert_not_called()

        # 6. If we age the records further, it should advance
        # Let's shift G222 from 3 days ago to 6 days ago (should trigger Day 5 reminder)
        rec_g222 = self.db.query(Record).filter(Record.code == "G222").first()
        rec_g222.send_time = now - datetime.timedelta(days=6)
        self.db.commit()

        await check_pending_reminders(mock_bot_app)
        self.assertEqual(mock_bot_app.bot.send_message.call_count, 1)
        
        sent_text_2 = mock_bot_app.bot.send_message.call_args[1]["text"]
        self.assertIn("G222", sent_text_2)
        self.assertNotIn("G555", sent_text_2) # G555 last_reminder_day is already 5, so no reminder trigger
        
        self.db.refresh(r_g222)
        self.assertEqual(r_g222.last_reminder_day, 5)

    def test_reminders_logic(self):
        import asyncio
        asyncio.run(self.async_test_reminders_logic())


class TestWebappCron(unittest.TestCase):
    def test_cron_reminders_route(self):
        from telegram_tracker.webapp import app
        from unittest.mock import patch

        with app.test_client() as client:
            with patch("telegram_tracker.webapp.run_async") as mock_run_async:
                # Test without CRON_SECRET set in environment
                with patch.dict("os.environ", {}, clear=False):
                    response = client.get("/cron/reminders")
                    self.assertEqual(response.status_code, 200)
                    self.assertEqual(response.data, b"Reminders checked successfully")
                    mock_run_async.assert_called_once()

                mock_run_async.reset_mock()
                
                # Test with CRON_SECRET set in environment
                with patch.dict("os.environ", {"CRON_SECRET": "my_secret_token"}, clear=False):
                    # 1. Missing header
                    response = client.get("/cron/reminders")
                    self.assertEqual(response.status_code, 401)
                    self.assertEqual(response.data, b"Unauthorized")
                    mock_run_async.assert_not_called()
                    
                    # 2. Incorrect header value
                    response = client.get("/cron/reminders", headers={"Authorization": "Bearer wrong_token"})
                    self.assertEqual(response.status_code, 401)
                    self.assertEqual(response.data, b"Unauthorized")
                    mock_run_async.assert_not_called()
                    
                    # 3. Correct header value
                    response = client.get("/cron/reminders", headers={"Authorization": "Bearer my_secret_token"})
                    self.assertEqual(response.status_code, 200)
                    self.assertEqual(response.data, b"Reminders checked successfully")
                    mock_run_async.assert_called_once()
class TestServiceCommands(unittest.TestCase):
    def setUp(self):
        from telegram_tracker.database import init_db, SessionLocal
        init_db()
        self.db = SessionLocal()

    def tearDown(self):
        self.db.close()
        from telegram_tracker.database import Base, engine
        Base.metadata.drop_all(bind=engine)
        engine.dispose()

    async def async_test_handlers(self):
        from telegram_tracker.handlers.admin import set_service, replace_service, reset_service
        # 1. Mock update and context
        update = MagicMock()
        update.effective_chat.id = -2001
        update.effective_chat.title = "Test CS Group"
        update.effective_chat.type = "group"
        update.effective_user.id = 999
        update.effective_user.username = "someuser"
        update.message.reply_text = AsyncMock()

        context = MagicMock()

        # Test /setservice with multiple users (should succeed)
        context.args = ["@cs1", "cs2", "@cs3"]
        await set_service(update, context)
        update.message.reply_text.assert_called_with(
            "✅ Added customer service member(s): @cs1, @cs2, @cs3.\nTotal members: @cs1 @cs2 @cs3"
        )

        # Check DB
        group = self.db.query(Group).filter(Group.id == -2001).first()
        self.assertIsNotNone(group)
        self.assertEqual(group.manager_tag, "@cs1 @cs2 @cs3")

        # Test /setservice adding more users up to the 4 limit (should succeed)
        update.message.reply_text.reset_mock()
        context.args = ["@cs4"]
        await set_service(update, context)
        update.message.reply_text.assert_called_with(
            "✅ Added customer service member(s): @cs4.\nTotal members: @cs1 @cs2 @cs3 @cs4"
        )
        self.db.refresh(group)
        self.assertEqual(group.manager_tag, "@cs1 @cs2 @cs3 @cs4")

        # Test /setservice adding a 5th user (should fail)
        update.message.reply_text.reset_mock()
        context.args = ["@cs5"]
        await set_service(update, context)
        update.message.reply_text.assert_called_with(
            "❌ Cannot add. Maximum of 4 customer service members is allowed.\nCurrent members: @cs1 @cs2 @cs3 @cs4"
        )
        self.db.refresh(group)
        self.assertEqual(group.manager_tag, "@cs1 @cs2 @cs3 @cs4") # unchanged

        # Test /replaceservice
        update.message.reply_text.reset_mock()
        context.args = ["@cs2", "@new_cs2"]
        await replace_service(update, context)
        update.message.reply_text.assert_called_with(
            "✅ Replaced @cs2 with @new_cs2.\nTotal members: @cs1 @new_cs2 @cs3 @cs4"
        )
        self.db.refresh(group)
        self.assertEqual(group.manager_tag, "@cs1 @new_cs2 @cs3 @cs4")

        # Test /replaceservice with non-existent old user
        update.message.reply_text.reset_mock()
        context.args = ["@cs_nonexistent", "@new_cs"]
        await replace_service(update, context)
        update.message.reply_text.assert_called_with(
            "❌ User @cs_nonexistent is not set as a customer service member in this group."
        )

        # Test /resetservice
        update.message.reply_text.reset_mock()
        await reset_service(update, context)
        update.message.reply_text.assert_called_with(
            "✅ Customer service members reset. No service members are set for this group."
        )
        self.db.refresh(group)
        self.assertIsNone(group.manager_tag)

        # Test /checkservice when NOT set
        from telegram_tracker.handlers.admin import check_service
        update.message.reply_text.reset_mock()
        await check_service(update, context)
        update.message.reply_text.assert_called_with(
            "មិនទាន់មានសមាជិកបម្រើអតិថិជនត្រូវបានកំណត់ឡើយទេ។"
        )

        # Test /checkservice when set
        context.args = ["@cs1", "@cs2"]
        await set_service(update, context)
        update.message.reply_text.reset_mock()
        await check_service(update, context)
        update.message.reply_text.assert_called_with(
            "សមាជិកបម្រើអតិថិជនបច្ចុប្បន្ន៖ @cs1 @cs2"
        )

    def test_handlers(self):
        import asyncio
        asyncio.run(self.async_test_handlers())


class TestWebappService(unittest.TestCase):
    def setUp(self):
        from telegram_tracker.database import init_db, SessionLocal
        init_db()
        self.db = SessionLocal()

    def tearDown(self):
        self.db.close()
        from telegram_tracker.database import Base, engine
        Base.metadata.drop_all(bind=engine)
        engine.dispose()

    def test_webapp_service_endpoints(self):
        from telegram_tracker.webapp import app
        from unittest.mock import patch

        with app.test_client() as client:
            # We mock the external bot send_message calls
            with patch("telegram_tracker.webapp.send_message_safely", new_callable=AsyncMock) as mock_send:
                # 1. Test /setservice
                payload = {
                    "message": {
                        "message_id": 123,
                        "chat": {"id": -3001, "title": "Webapp CS Group", "type": "group"},
                        "from": {"id": 100, "username": "any_user"},
                        "text": "/setservice @w1 w2 @w3"
                    }
                }
                response = client.post("/webhook", json=payload)
                self.assertEqual(response.status_code, 200)
                
                # Check DB
                group = self.db.query(Group).filter(Group.id == -3001).first()
                self.assertIsNotNone(group)
                self.assertEqual(group.manager_tag, "@w1 @w2 @w3")
                
                # Verify reply message contains the success
                mock_send.assert_called_with(
                    -3001,
                    "✅ Added customer service member(s): @w1, @w2, @w3.\nTotal members: @w1 @w2 @w3",
                    reply_to_message_id=123
                )

                # 2. Test /replaceservice
                payload["message"]["text"] = "/replaceservice @w2 @new_w2"
                response = client.post("/webhook", json=payload)
                self.assertEqual(response.status_code, 200)
                
                self.db.refresh(group)
                self.assertEqual(group.manager_tag, "@w1 @new_w2 @w3")

                # 3. Test /resetservice
                payload["message"]["text"] = "/resetservice"
                response = client.post("/webhook", json=payload)
                self.assertEqual(response.status_code, 200)
                
                self.db.refresh(group)
                self.assertIsNone(group.manager_tag)

                # 4. Test /reminders
                payload["message"]["text"] = "/reminders"
                response = client.post("/webhook", json=payload)
                self.assertEqual(response.status_code, 200)

    def test_webapp_my_chat_member(self):
        from telegram_tracker.webapp import app, GUIDE_TEXT
        from unittest.mock import patch

        with app.test_client() as client:
            with patch("telegram_tracker.webapp.send_message_safely", new_callable=AsyncMock) as mock_send:
                payload = {
                    "my_chat_member": {
                        "chat": {"id": -4001, "title": "Webapp My Chat Member Group", "type": "group"},
                        "from": {"id": 100, "username": "any_user"},
                        "old_chat_member": {
                            "user": {"id": 9999, "is_bot": True, "first_name": "TestBot"},
                            "status": "left"
                        },
                        "new_chat_member": {
                            "user": {"id": 9999, "is_bot": True, "first_name": "TestBot"},
                            "status": "member"
                        }
                    }
                }
                response = client.post("/webhook", json=payload)
                self.assertEqual(response.status_code, 200)
                mock_send.assert_called_with(-4001, GUIDE_TEXT, parse_mode="Markdown")

    def test_webapp_edited_message(self):
        from telegram_tracker.webapp import app
        from unittest.mock import patch

        with app.test_client() as client:
            with patch("telegram_tracker.webapp.send_message_safely", new_callable=AsyncMock) as mock_send:
                payload = {
                    "edited_message": {
                        "message_id": 456,
                        "chat": {"id": -3002, "title": "Webapp Edited Group", "type": "group"},
                        "from": {"id": 100, "username": "any_user", "first_name": "Alice"},
                        "text": "G5555 cut"
                    }
                }
                response = client.post("/webhook", json=payload)
                self.assertEqual(response.status_code, 200)
                
                # Check DB
                group = self.db.query(Group).filter(Group.id == -3002).first()
                self.assertIsNotNone(group)
                
                record = self.db.query(Record).filter(Record.group_id == -3002, Record.code == "G5555").first()
                self.assertIsNotNone(record)
                self.assertEqual(record.status, "SENT")
                
                # Verify mock reply
                mock_send.assert_called_once()


class TestMyChatMemberHandler(unittest.TestCase):
    async def async_test_handle_my_chat_member(self):
        from telegram_tracker.handlers.message import handle_my_chat_member
        from telegram_tracker.handlers.admin import GUIDE_TEXT
        from unittest.mock import AsyncMock, MagicMock
        
        # Scenario 1: Bot joins group
        update = MagicMock()
        update.my_chat_member.chat.id = -5001
        update.my_chat_member.chat.type = "group"
        update.my_chat_member.old_chat_member.status = "left"
        update.my_chat_member.new_chat_member.status = "member"
        
        context = MagicMock()
        context.bot.send_message = AsyncMock()
        
        await handle_my_chat_member(update, context)
        context.bot.send_message.assert_called_with(
            chat_id=-5001,
            text=GUIDE_TEXT,
            parse_mode="Markdown"
        )
        
        # Scenario 2: Bot is already member, status changes to admin (should not send guide again)
        context.bot.send_message.reset_mock()
        update.my_chat_member.old_chat_member.status = "member"
        update.my_chat_member.new_chat_member.status = "administrator"
        await handle_my_chat_member(update, context)
        context.bot.send_message.assert_not_called()

        # Scenario 3: Bot leaves group (status member -> left) (should not send guide)
        context.bot.send_message.reset_mock()
        update.my_chat_member.old_chat_member.status = "member"
        update.my_chat_member.new_chat_member.status = "left"
        await handle_my_chat_member(update, context)
        context.bot.send_message.assert_not_called()

    def test_handle_my_chat_member(self):
        import asyncio
        asyncio.run(self.async_test_handle_my_chat_member())


class TestKhmerFormatting(unittest.TestCase):
    def setUp(self):
        from telegram_tracker.database import init_db, SessionLocal
        init_db()
        self.db = SessionLocal()

    def tearDown(self):
        self.db.close()
        from telegram_tracker.database import Base, engine
        Base.metadata.drop_all(bind=engine)
        engine.dispose()

    async def async_test_khmer_message_responses(self):
        from telegram_tracker.handlers.message import handle_group_message
        from unittest.mock import AsyncMock, MagicMock, patch

        # Mock update
        update = MagicMock()
        update.effective_chat.id = -6001
        update.effective_chat.title = "Khmer Test Group"
        update.effective_chat.type = "group"
        update.effective_user.id = 777
        update.effective_user.username = "userA"
        update.effective_user.first_name = "User"
        update.effective_user.last_name = "A"
        update.effective_message.text = "G26555442232 G35566555442 cut"
        
        context = MagicMock()

        # Mock reply_safely to capture the response text
        with patch("telegram_tracker.handlers.message.reply_safely", new_callable=AsyncMock) as mock_reply:
            # Run multi-code SENT
            await handle_group_message(update, context)
            
            mock_reply.assert_called_once()
            called_args = mock_reply.call_args[0]
            response_text = called_args[1]
            
            self.assertIn("កត់ត្រាកូដដែលបានកាត់ថ្លៃដើម (ចំនួន 2កូដថ្មី)", response_text)
            self.assertIn("• G26555442232", response_text)
            self.assertIn("• G35566555442", response_text)
            self.assertIn("ស្ថានភាព៖ មិនទាន់បានទទួល", response_text)
            self.assertIn("អ្នកផ្ញើកូដ៖ User A", response_text)

            # Reset mock for single-code SENT
            mock_reply.reset_mock()
            update.effective_message.text = "G11111 cut"
            await handle_group_message(update, context)
            
            mock_reply.assert_called_once()
            response_text_single = mock_reply.call_args[0][1]
            self.assertIn("កត់ត្រាកូដដែលបានកាត់ថ្លៃដើម (ចំនួន 1កូដថ្មី)", response_text_single)
            self.assertIn("លេខបេ៖ G11111", response_text_single)

    def test_khmer_message_responses(self):
        import asyncio
        asyncio.run(self.async_test_khmer_message_responses())

    async def async_test_khmer_pending_response(self):
        from telegram_tracker.handlers.admin import list_pending
        from telegram_tracker.handlers.message import handle_group_message
        from unittest.mock import AsyncMock, MagicMock, patch

        # 1. Setup database records using handle_group_message
        update = MagicMock()
        update.effective_chat.id = -6002
        update.effective_chat.title = "Pending Test Group"
        update.effective_chat.type = "group"
        update.effective_user.id = 888
        update.effective_user.username = "userB"
        update.effective_user.first_name = "User"
        update.effective_user.last_name = "B"
        update.effective_message.text = "G26555442233 G26555442232 cut"
        
        context = MagicMock()

        # Send/Record the codes first
        with patch("telegram_tracker.handlers.message.reply_safely", new_callable=AsyncMock):
            await handle_group_message(update, context)

        # 2. Call list_pending to view the list and assert Khmer output
        update_cmd = MagicMock()
        update_cmd.effective_chat.id = -6002
        update_cmd.effective_chat.type = "group"
        update_cmd.message.reply_text = AsyncMock()

        with patch("telegram_tracker.handlers.admin.reply_safely", new_callable=AsyncMock) as mock_reply:
            await list_pending(update_cmd, context)
            
            mock_reply.assert_called_once()
            response_text = mock_reply.call_args[0][1]
            
            self.assertIn("📋កំណត់ត្រាលេខកូដបេដែលមិនទាន់ទទួលបាន (ចំនួន 2កូដ)", response_text)
            self.assertIn("កាលបរិច្ឆេទដែលបានកាត់ថ្លៃដើម៖", response_text)
            self.assertIn("លេខបេដែលមិនទាន់ទទួលបាន៖", response_text)
            self.assertIn("• G26555442232", response_text)
            self.assertIn("• G26555442233", response_text)
            self.assertIn("ស្ថានភាព៖ មិនទាន់ទទួលបាន", response_text)

    def test_khmer_pending_response(self):
        import asyncio
        asyncio.run(self.async_test_khmer_pending_response())

    async def async_test_khmer_find_response(self):
        from telegram_tracker.handlers.admin import find_code
        from telegram_tracker.handlers.message import handle_group_message
        from telegram_tracker.database import SessionLocal
        from unittest.mock import AsyncMock, MagicMock, patch

        # 1. Setup a group manager tag, and record codes
        from telegram_tracker.services.tracker import upsert_group
        db = SessionLocal()
        group = upsert_group(db, -6003, "Find Test Group")
        group.manager_tag = "@cs1 @cs2"
        db.commit()
        db.close()

        update = MagicMock()
        update.effective_chat.id = -6003
        update.effective_chat.title = "Find Test Group"
        update.effective_chat.type = "group"
        update.effective_user.id = 888
        update.effective_user.username = "userB"
        update.effective_user.first_name = "User"
        update.effective_user.last_name = "B"
        # Submit G26062588521 cut (PENDING)
        update.effective_message.text = "G26062588521 cut"
        
        context = MagicMock()

        with patch("telegram_tracker.handlers.message.reply_safely", new_callable=AsyncMock):
            await handle_group_message(update, context)

        # 2. Call find_code to search multiple codes (including non-existent and pending)
        update_cmd = MagicMock()
        update_cmd.effective_chat.id = -6003
        update_cmd.effective_chat.title = "Find Test Group"
        update_cmd.effective_chat.type = "group"
        update_cmd.effective_message.text = "/find G26062588521 G99999999999"
        update_cmd.message.reply_text = AsyncMock()
        context_cmd = MagicMock()

        with patch("telegram_tracker.handlers.admin.reply_safely", new_callable=AsyncMock) as mock_reply:
            await find_code(update_cmd, context_cmd)
            
            mock_reply.assert_called_once()
            response_text = mock_reply.call_args[0][1]
            
            # Check Khmer layout content
            self.assertIn("ទិន្នន័យដែលបានឆែក៖", response_text)
            self.assertIn("-----------------------", response_text)
            self.assertIn("G26062588521", response_text)
            self.assertIn("🔸ស្ថានភាព៖ មិនទាន់បានទទួល", response_text)
            self.assertIn("📅កាលបរិច្ឆេទកាត់ថ្លៃដើម៖", response_text)
            self.assertIn("📅 Pending:", response_text)
            
            self.assertIn("G99999999999", response_text)
            self.assertIn("🔸ស្ថានភាព៖ រកមិនឃើញ", response_text)
            
            # Check follow up trailer
            self.assertIn("សូមជួយឆែកនិងតាមឥវ៉ាន់លេខបេ៖", response_text)
            self.assertIn("G26062588521", response_text)
            self.assertIn("សូមអរគុណ @cs1 @cs2", response_text)

    def test_khmer_find_response(self):
        import asyncio
        asyncio.run(self.async_test_khmer_find_response())

    async def async_test_khmer_reminders_command(self):
        from telegram_tracker.handlers.admin import show_reminders
        from telegram_tracker.handlers.message import handle_group_message
        from telegram_tracker.database import SessionLocal
        from telegram_tracker.models.reminder import Reminder
        from unittest.mock import AsyncMock, MagicMock, patch

        # 1. Setup records
        update = MagicMock()
        update.effective_chat.id = -6004
        update.effective_chat.title = "Reminder Cmd Group"
        update.effective_chat.type = "group"
        update.effective_user.id = 888
        update.effective_user.username = "userB"
        update.effective_user.first_name = "User"
        update.effective_user.last_name = "B"
        update.effective_message.text = "G111 cut"
        context = MagicMock()

        # Submit code first
        with patch("telegram_tracker.handlers.message.reply_safely", new_callable=AsyncMock):
            await handle_group_message(update, context)

        # Set G111 send_time to 3 days ago and create a Reminder tracker record for G111 (last_reminder_day=2)
        db = SessionLocal()
        rec = db.query(Record).filter(Record.group_id == -6004, Record.code == "G111").first()
        rec.send_time = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None) - datetime.timedelta(days=3)
        rem = Reminder(group_id=-6004, code="G111", last_reminder_day=2)
        db.add(rem)
        db.commit()
        db.close()

        # 2. Call show_reminders command
        update_cmd = MagicMock()
        update_cmd.effective_chat.id = -6004
        update_cmd.effective_chat.type = "group"
        update_cmd.message.reply_text = AsyncMock()

        with patch("telegram_tracker.handlers.admin.reply_safely", new_callable=AsyncMock) as mock_reply:
            await show_reminders(update_cmd, context)
            
            mock_reply.assert_called_once()
            response_text = mock_reply.call_args[0][1]
            
            self.assertIn("ស្ថានភាពការរំលឹកលេខកូដបេ", response_text)
            self.assertIn("លេខកូដដែលបានរំលឹករួច", response_text)
            self.assertIn("លេខកូដដែលនឹងត្រូវរំលឹកឆាប់ៗ", response_text)
            self.assertIn("បានរំលឹក 2ថ្ងៃ | រយៈពេល៖ 3ថ្ងៃ៖", response_text)
            self.assertIn("នឹងរំលឹក (Day 5)", response_text)
            self.assertIn("• G111", response_text)

    def test_khmer_reminders_command(self):
        import asyncio
        asyncio.run(self.async_test_khmer_reminders_command())


if __name__ == "__main__":
    unittest.main()
