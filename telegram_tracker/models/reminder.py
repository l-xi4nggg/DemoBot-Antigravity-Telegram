from sqlalchemy import BigInteger, String, Integer, ForeignKeyConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from telegram_tracker.database import Base

class Reminder(Base):
    __tablename__ = "reminders"

    group_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    code: Mapped[str] = mapped_column(String(100), primary_key=True)
    last_reminder_day: Mapped[int] = mapped_column(Integer, default=0)

    # Composite foreign key constraint to link directly to records
    __table_args__ = (
        ForeignKeyConstraint(
            ["group_id", "code"],
            ["records.group_id", "records.code"],
            ondelete="CASCADE"
        ),
    )

    # Relationship back to record
    record: Mapped["Record"] = relationship("Record")

    def __repr__(self) -> str:
        return f"<Reminder group_id={self.group_id} code={self.code!r} last_reminder_day={self.last_reminder_day}>"
