"""Utils module."""

import logging
import time

from flask import current_app


def get_current_timestamp():
    """Return the current timestamp in seconds as a (rounded) integer."""
    return round(time.time())


def get_logger(name):
    """Return a logger instance with the provided name and DEBUG level."""
    logger = logging.getLogger(name)
    logger.setLevel(logging.DEBUG)
    return logger


def get_rgb_asset(asset_id):
    """Return the RGB asset with the given ID and its schema, if found."""
    wallet = current_app.config["WALLET"]
    assets = wallet.list_assets([])
    for schema in ('rgb20', 'rgb121'):
        for asset in getattr(assets, schema):
            if asset.asset_id == asset_id:
                return asset, schema.upper()
    return None, None


def get_asset_dict(assets):
    """Return a dict of the available assets."""
    asset_dict = {}
    for asset in assets:
        asset_dict[asset.asset_id] = {
            'balance': {
                'settled': asset.balance.settled,
                'future': asset.balance.future
            },
            'name': asset.name,
            'precision': asset.precision,
        }
        if hasattr(asset, 'ticker'):
            asset_dict[asset.asset_id]['ticker'] = asset.ticker
        if hasattr(asset, 'description'):
            asset_dict[asset.asset_id]['description'] = asset.description
        if hasattr(asset, 'parent_id'):
            asset_dict[asset.asset_id]['parent_id'] = asset.parent_id
        if hasattr(asset, 'data_paths'):
            for data_path in asset.data_paths:
                path_list = asset_dict[asset.asset_id].setdefault(
                    'data_paths', [])
                attachment_id = data_path.file_path.split('/')[-2]
                path_list.append({
                    'mime-type': data_path.mime,
                    'attachment_id': attachment_id,
                })
    return asset_dict
