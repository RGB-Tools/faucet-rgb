"""Default application settings."""

from flask_migrate import Migrate
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import Integer, String, func
from sqlalchemy.sql.functions import Function
from sqlalchemy.orm import Mapped, mapped_column

from .utils import get_current_timestamp

db = SQLAlchemy()  # pylint: disable=invalid-name
migrate = Migrate()

COUNT_FUNC: Function[int] = func.count()  # pylint: disable=not-callable

STATUS_MAP = {
    10: "new",
    20: "pending",
    25: "waiting",
    30: "processing",
    40: "served",
    45: "unmet",
}


class Request(db.Model):  # pylint: disable=too-few-public-methods,too-many-instance-attributes
    """Request model."""

    idx: Mapped[int] = mapped_column(Integer, primary_key=True)
    timestamp: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[int] = mapped_column(Integer, nullable=False)
    wallet_id: Mapped[str] = mapped_column(String(256), nullable=False)
    recipient_id: Mapped[str] = mapped_column(String(256), nullable=False)
    invoice: Mapped[str] = mapped_column(String(256), nullable=False)
    asset_group: Mapped[str] = mapped_column(String(256), nullable=False)
    asset_id: Mapped[str] = mapped_column(String(256), nullable=True)
    amount: Mapped[int] = mapped_column(Integer, nullable=True)

    # pylint: disable=too-many-positional-arguments
    def __init__(
        self,
        wallet_id: str,
        recipient_id: str,
        invoice: str,
        asset_group: str,
        asset_id: str,
        amount: int,
    ):
        # pylint: disable=too-many-arguments
        self.timestamp = get_current_timestamp()
        self.status = 10
        self.wallet_id = wallet_id
        self.recipient_id = recipient_id
        self.invoice = invoice
        self.asset_group = asset_group
        self.asset_id = asset_id
        self.amount = amount

    def __str__(self):
        return (
            f"{STATUS_MAP[self.status]} {self.timestamp} "
            f"{self.wallet_id} {self.recipient_id} {self.invoice} "
            f"{self.asset_group} {self.asset_id} {self.amount}"
        )


def count_query(*conditions):
    """Count Request rows based on provided conditions."""
    return db.select(COUNT_FUNC).select_from(Request).where(*conditions)


def delete_query(*conditions):
    """Delete Request rows based on provided conditions."""
    return db.delete(Request).where(*conditions)


def select_query(*conditions):
    """Select Request rows based on provided conditions."""
    return db.select(Request).where(*conditions)


def update_query(*conditions):
    """Select Request rows to be updated based on provided conditions."""
    return db.update(Request).where(*conditions)
