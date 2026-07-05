import datetime
from sqlalchemy import BigInteger, String, DateTime, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship
from telegram_tracker.database import Base

class Record(Base):
    __tablename__ = "records"

    # Multi-group key: (group_id, code) is the primary key
    group_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("groups.id"), primary_key=True)
    code: Mapped[str] = mapped_column(String(100), primary_key=True)
    
    status: Mapped[str] = mapped_column(String(50), default="SENT")  # "SENT" or "RECEIVED"
    
    sender_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"))
    receiver_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("users.id"), nullable=True)
    
    send_time: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True))
    receive_time: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Relationships
    group: Mapped["Group"] = relationship("Group")
    sender: Mapped["User"] = relationship("User", foreign_keys=[sender_id])
    receiver: Mapped["User | None"] = relationship("User", foreign_keys=[receiver_id])

    def __repr__(self) -> str:
        return f"<Record group_id={self.group_id} code={self.code!r} status={self.status!r}>"
