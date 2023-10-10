"""Utils module."""

import logging
import time

import rgb_lib
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
    for schema in ('nia', 'cfa'):
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


def get_recipient(invoice, amount, cfg):
    """Return a recipient for the given invoice."""
    invoice_data = rgb_lib.Invoice(invoice).invoice_data()
    recipient_id = invoice_data.recipient_id
    # detect if blinded UTXO or script (witness tx)
    blinded_utxo = True
    try:
        rgb_lib.BlindedUtxo(recipient_id)
    except rgb_lib.RgbLibError:  # pylint: disable=catching-non-exception
        blinded_utxo = False
    # create Recipient
    if blinded_utxo:
        recipient = rgb_lib.Recipient(recipient_id, None, amount,
                                      invoice_data.transport_endpoints)
    else:
        script_data = rgb_lib.ScriptData(recipient_id, cfg['AMOUNT_SAT'], None)
        recipient = rgb_lib.Recipient(None, script_data, amount,
                                      invoice_data.transport_endpoints)
    return recipient
