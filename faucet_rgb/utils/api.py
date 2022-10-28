"""API utils module."""

import random

import rgb_lib
from flask import current_app

from ..database import Request


def is_send_possible(asset_list, blinded_utxo):
    """Return if the given blinded UTXO is valid or not."""
    cfg = {}
    cfg['online'] = current_app.config['ONLINE']
    cfg['wallet'] = current_app.config['WALLET']
    cfg['req_number'] = current_app.config['MIN_REQUESTS']

    possible = False
    asset = None
    error = None
    assets = list(asset_list)  # use a copy lest changing global configuration
    while assets:
        asset = random.choice(assets)
        assets.remove(asset)

        # sum amounts for the same asset from pending requests in next batch
        req_batch = Request.query.filter(
            Request.status == 20, Request.asset_id == asset['asset_id']).slice(
                0, cfg['req_number']).all()
        amount = asset['amount']
        for request in req_batch:
            amount += request.amount

        try:
            current_app.logger.debug(
                f'trying asset: {asset} with total amount: {amount}')
            recipient_map = {
                asset['asset_id']: [rgb_lib.Recipient(blinded_utxo, amount)]
            }
            cfg['wallet'].send_begin(cfg['online'], recipient_map, False)
            possible = True
        except rgb_lib.RgbLibError.InvalidBlindedUtxo as err:
            error = 'Invalid blinded UTXO'
            current_app.logger.info(f'{err} ({blinded_utxo})')
        except rgb_lib.RgbLibError.BlindedUtxoAlreadyUsed as err:
            error = 'Blinded UTXO already used'
            current_app.logger.info(err)
        except rgb_lib.RgbLibError.InsufficientAssets as err:
            error = 'Insufficient assets'
            current_app.logger.info(err)
        except rgb_lib.RgbLibError.InsufficientAllocationSlots:
            error = 'Insufficient allocation slots'
            current_app.logger.info(f'{error}, creating a new UTXO')
            cfg['wallet'].create_utxos(cfg['online'], False, 3)
            assets.append(asset)

    return possible, asset, error
