from sqlalchemy import BigInteger, String
from sqlalchemy.orm import Mapped, mapped_column
from telegram_tracker.database import Base

class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    username: Mapped[str | None] = mapped_column(String(100), nullable=True)
    first_name: Mapped[str] = mapped_column(String(150))
    last_name: Mapped[str | None] = mapped_column(String(150), nullable=True)

    @property
    def full_name(self) -> str:
        if self.last_name:
            return f"{self.first_name} {self.last_name}"
        return self.first_name

    @property
    def display_name(self) -> str:
        """Returns the username formatted or the full name if username is missing"""
        if self.username:
            return f"@{self.username}"
        return self.full_name

    def __repr__(self) -> str:
        return f"<User id={self.id} username={self.username!r} first_name={self.first_name!r}>"
