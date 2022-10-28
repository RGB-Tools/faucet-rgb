"""Utils module."""

import time

from flask import current_app


def get_current_timestamp():
    """Return the current timestamp in seconds as a (rounded) integer."""
    return round(time.time())


def get_rgb_asset(asset_id):
    """Return the RGB asset with the given ID and its schema, if found."""
    wallet = current_app.config["WALLET"]
    assets = wallet.list_assets([])
    for schema in ('rgb20', 'rgb21'):
        for asset in getattr(assets, schema):
            if asset.asset_id == asset_id:
                return asset, schema.upper()
    return None, None
