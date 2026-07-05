import datetime
from typing import Tuple, Optional
from sqlalchemy.orm import Session
from telegram_tracker.models.user import User
from telegram_tracker.models.group import Group
from telegram_tracker.models.record import Record

def upsert_user(
    db: Session,
    user_id: int,
    username: Optional[str],
    first_name: str,
    last_name: Optional[str]
) -> User:
    """Upserts a user to database, updating fields if they changed."""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        user = User(
            id=user_id,
            username=username,
            first_name=first_name,
            last_name=last_name
        )
        db.add(user)
    else:
        user.username = username
        user.first_name = first_name
        user.last_name = last_name
    db.flush()
    return user

def upsert_group(db: Session, group_id: int, title: str) -> Group:
    """Upserts a group to database, updating the title if changed."""
    group = db.query(Group).filter(Group.id == group_id).first()
    if not group:
        group = Group(id=group_id, title=title)
        db.add(group)
    else:
        group.title = title
    db.flush()
    return group

def record_submission(
    db: Session,
    group_id: int,
    code: str,
    sender_id: int,
    send_time: datetime.datetime
) -> Tuple[Record, bool]:
    """
    Records a code submission (status = SENT).
    Returns a tuple of (Record, is_new).
    If the code already exists for this group, returns (existing_record, False).
    """
    record = db.query(Record).filter(
        Record.group_id == group_id, 
        Record.code == code
    ).first()
    
    if record:
        return record, False
        
    record = Record(
        group_id=group_id,
        code=code,
        status="SENT",
        sender_id=sender_id,
        send_time=send_time
    )
    db.add(record)
    db.flush()
    return record, True

def record_receipt(
    db: Session,
    group_id: int,
    code: str,
    receiver_id: int,
    receive_time: datetime.datetime
) -> Optional[Record]:
    """
    Updates a record to RECEIVED.
    Returns the updated Record, or None if the record was not found in this group.
    """
    record = db.query(Record).filter(
        Record.group_id == group_id, 
        Record.code == code
    ).first()
    
    if not record:
        return None
        
    record.status = "RECEIVED"
    record.receiver_id = receiver_id
    record.receive_time = receive_time
    db.flush()
    return record
