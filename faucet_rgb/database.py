"""Default application settings."""

from flask_migrate import Migrate
from flask_sqlalchemy import SQLAlchemy

from .utils import get_current_timestamp

db = SQLAlchemy()  # pylint: disable=invalid-name
migrate = Migrate()

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

    idx = db.Column(db.Integer, primary_key=True)
    timestamp = db.Column(db.Integer, nullable=False)
    status = db.Column(db.Integer, nullable=False)
    wallet_id = db.Column(db.String(256), nullable=False)
    recipient_id = db.Column(db.String(256), nullable=False)
    invoice = db.Column(db.String(256), nullable=False)
    asset_group = db.Column(db.String(256), nullable=False)
    asset_id = db.Column(db.String(256), nullable=True)
    amount = db.Column(db.Integer, nullable=True)

    # pylint: disable=too-many-arguments
    def __init__(self, wallet_id, recipient_id, invoice, asset_group, asset_id, amount):
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
