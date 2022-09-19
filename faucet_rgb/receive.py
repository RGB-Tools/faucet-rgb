"""Faucet blueprint to top-up funds."""

import random

from flask import Blueprint, current_app, jsonify, request
import rgb_lib

bp = Blueprint('receive', __name__, url_prefix='/receive')


@bp.route('/<blinded_utxo>', methods=['GET'])
def send_btc(blinded_utxo):
    """Send configured amount to provided blinded UTXO."""
    headers = request.headers
    auth = headers.get('X-Api-Key')
    if auth != current_app.config['API_KEY']:
        return jsonify({'error': 'unauthorized'}), 401

    print(f'Request for blinded UTXO: {blinded_utxo}')

    assets = current_app.config["ASSETS"]
    asset_group = request.args.get('asset_group')
    if asset_group is not None:
        if asset_group not in assets:
            return jsonify({'error': 'Invalid asset group'}), 404
    else:
        asset_group = random.choice(list(assets))

    group_assets = assets[asset_group]
    asset = random.choice(group_assets)
    print(f'Sending asset: {asset}')

    online = current_app.config["ONLINE"]
    wallet = current_app.config["WALLET"]
    try:
        txid = wallet.send(online, asset['asset_id'], blinded_utxo, asset['amount'])
        return jsonify({'txid': txid})
    except rgb_lib.RgbLibError.InsufficientAssets:
        return jsonify({'error': 'Faucet funds are exhausted'})
    except Exception as err:
        return jsonify({'error': f'Unknown error: {err}'})


@bp.route('/refresh/<asset_id>', methods=['GET'])
def refresh(asset_id):
    """Refresh asset."""
    print(f'Refreshing asset with ID {asset_id}')
    online = current_app.config["ONLINE"]
    wallet = current_app.config["WALLET"]
    try:
        wallet.refresh(online, asset_id)
        return jsonify('Success')
    except Exception as err:
        return jsonify({'error': f'Unknown error: {err}'})
