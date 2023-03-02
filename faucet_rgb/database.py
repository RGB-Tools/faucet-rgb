"""Default application settings."""

from flask_sqlalchemy import SQLAlchemy

from .utils import get_current_timestamp

db = SQLAlchemy()  # pylint: disable=invalid-name

STATUS_MAP = {
    10: "new",
    20: "pending",
    30: "processing",
    40: "served",
}


class Request(db.Model):  # pylint: disable=too-few-public-methods
    """Request model."""
    idx = db.Column(db.Integer, primary_key=True)
    timestamp = db.Column(db.Integer, nullable=False)
    status = db.Column(db.Integer, nullable=False)
    wallet_id = db.Column(db.String(256), nullable=False)
    blinded_utxo = db.Column(db.String(256), nullable=False)
    asset_group = db.Column(db.String(256), nullable=False)
    asset_id = db.Column(db.String(256), nullable=True)
    amount = db.Column(db.Integer, nullable=True)
    reissuance_of = db.Column(db.Integer, nullable = True)

    def __init__(self, wallet_id, blinded_utxo, asset_group, asset_id, amount, reissuance_of = None):  # pylint: disable=too-many-arguments
        self.timestamp = get_current_timestamp()
        self.status = 10
        self.wallet_id = wallet_id
        self.blinded_utxo = blinded_utxo
        self.asset_group = asset_group
        self.asset_id = asset_id
        self.amount = amount
        self.reissuance_of = reissuance_of

    def __str__(self):
        return (f'{STATUS_MAP[self.status]} '
                f'{self.timestamp} {self.wallet_id} {self.blinded_utxo} '
                f'{self.asset_group} {self.asset_id} {self.amount} '
                f'{self.reissuance_of}')
