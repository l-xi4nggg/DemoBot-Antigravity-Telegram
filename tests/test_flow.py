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
        # We expect 3 send_message calls (for G222, G555, G777)
        self.assertEqual(mock_bot_app.bot.send_message.call_count, 3)

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


if __name__ == "__main__":
    unittest.main()
