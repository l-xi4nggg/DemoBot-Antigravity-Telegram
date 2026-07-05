from sqlalchemy import BigInteger, String
from sqlalchemy.orm import Mapped, mapped_column
from telegram_tracker.database import Base

class Group(Base):
    __tablename__ = "groups"

    # Telegram group IDs are large negative integers (e.g. -100123456789)
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    title: Mapped[str] = mapped_column(String(255))
    manager_tag: Mapped[str | None] = mapped_column(String(255), nullable=True)

    def __repr__(self) -> str:
        return f"<Group id={self.id} title={self.title!r} manager_tag={self.manager_tag!r}>"
