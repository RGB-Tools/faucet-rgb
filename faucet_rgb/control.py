"""Faucet blueprint to top-up funds."""

from flask import Blueprint, current_app, jsonify, request
from rgb_lib import TransferStatus

bp = Blueprint('control', __name__, url_prefix='/control')


@bp.route('/assets', methods=['GET'])
def assets():
    """Return the list of RGB assets from rgb-lib."""
    auth = request.headers.get('X-Api-Key')
    if auth != current_app.config['API_KEY_OPERATOR']:
        return jsonify({'error': 'unauthorized'}), 401

    online = current_app.config["ONLINE"]
    wallet = current_app.config["WALLET"]
    wallet.refresh(online, None)
    asset_list = wallet.list_assets([])
    asset_dict = {}
    for asset in asset_list.rgb20 + asset_list.rgb21:
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
                print('data path', data_path, type(data_path))
                path_list = asset_dict[asset.asset_id].setdefault(
                    'data_paths', [])
                path_list.append({
                    'mime-type': data_path.mime,
                    'path': data_path.file_path,
                })
    return jsonify({'assets': asset_dict})


@bp.route('/delete', methods=['GET'])
def delete_transfers():
    """Delete currently failed transfers."""
    auth = request.headers.get('X-Api-Key')
    if auth != current_app.config['API_KEY_OPERATOR']:
        return jsonify({'error': 'unauthorized'}), 401

    wallet = current_app.config["WALLET"]
    wallet.delete_transfers(None, None)
    return jsonify({}), 204


@bp.route('/fail', methods=['GET'])
def fail_transfers():
    """Fail currently pending transfers."""
    auth = request.headers.get('X-Api-Key')
    if auth != current_app.config['API_KEY_OPERATOR']:
        return jsonify({'error': 'unauthorized'}), 401

    online = current_app.config["ONLINE"]
    wallet = current_app.config["WALLET"]
    wallet.fail_transfers(online, None, None)
    return jsonify({}), 204


@bp.route('/transfers', methods=['GET'])
def list_transfers():
    """List asset transfers.

    Only transfers with an asset ID are queried, as the asset_id parameter to
    the list_transfers rgb-lib API is mandatory.

    Pending transfers are listed by default. If a valid status is provided via
    query parameter, then transfers in that status are returned instead.
    """
    auth = request.headers.get('X-Api-Key')
    if auth != current_app.config['API_KEY_OPERATOR']:
        return jsonify({'error': 'unauthorized'}), 401

    # set status filter from query parameter or default to pending ones
    status_filter = [
        TransferStatus.WAITING_COUNTERPARTY,
        TransferStatus.WAITING_CONFIRMATIONS
    ]
    status = request.args.get('status')
    if status is not None:
        if not hasattr(TransferStatus, status.upper()):
            return jsonify({'error':
                            f'unknown status requested: {status}'}), 403
        status_filter = [getattr(TransferStatus, status.upper())]

    # refresh and list transfers in matching status(es)
    online = current_app.config["ONLINE"]
    wallet = current_app.config["WALLET"]
    wallet.refresh(online, None)
    asset_list = wallet.list_assets([])
    asset_ids = [a.asset_id for a in asset_list.rgb20 + asset_list.rgb21]
    transfers = []
    for asset_id in asset_ids:
        asset_transfers = wallet.list_transfers(asset_id)
        for transfer in asset_transfers:
            if transfer.status not in status_filter:
                continue
            transfers.append({
                'status': transfer.status.name,
                'amount': transfer.amount,
                'incoming': transfer.incoming,
                'txid': transfer.txid,
                'blinded_utxo': transfer.blinded_utxo,
            })
    return jsonify({'transfers': transfers})


@bp.route('/refresh/<asset_id>', methods=['GET'])
def refresh(asset_id):
    """Refresh asset."""
    auth = request.headers.get('X-Api-Key')
    if auth != current_app.config['API_KEY_OPERATOR']:
        return jsonify({'error': 'unauthorized'}), 401

    online = current_app.config["ONLINE"]
    wallet = current_app.config["WALLET"]
    try:
        wallet.refresh(online, asset_id)
        return jsonify('{}'), 204
    except Exception as err:  # pylint: disable=broad-except
        return jsonify({'error': f'Unknown error: {err}'}), 500


@bp.route('/unspents', methods=['GET'])
def unspents():
    """Return an address to top-up the faucet's Bitcoin reserve."""
    auth = request.headers.get('X-Api-Key')
    if auth != current_app.config['API_KEY_OPERATOR']:
        return jsonify({'error': 'unauthorized'}), 401

    online = current_app.config["ONLINE"]
    wallet = current_app.config["WALLET"]
    wallet.refresh(online, None)
    unspent_list = wallet.list_unspents(False)
    unspent_dict = {}
    for unspent in unspent_list:
        unspent_dict[str(
            unspent.utxo)] = [str(a) for a in unspent.rgb_allocations]
    return jsonify({'unspents': unspent_dict})
