"""Faucet blueprint to top-up funds."""

from flask import Blueprint, current_app, jsonify, request
from rgb_lib import TransferStatus

from faucet_rgb import utils

bp = Blueprint('control', __name__, url_prefix='/control')


@bp.route('/assets', methods=['GET'])
def assets():
    """Return the list of RGB assets from rgb-lib."""
    auth = request.headers.get('X-Api-Key')
    if auth != current_app.config['API_KEY_OPERATOR']:
        return jsonify({'error': 'unauthorized'}), 401

    online = current_app.config["ONLINE"]
    wallet = current_app.config["WALLET"]
    wallet.refresh(online, None, [])
    asset_list = wallet.list_assets([])
    asset_dict = utils.get_asset_dict(asset_list.nia + asset_list.cfa)
    return jsonify({'assets': asset_dict})


@bp.route('/delete', methods=['GET'])
def delete_transfers():
    """Delete currently failed transfers."""
    auth = request.headers.get('X-Api-Key')
    if auth != current_app.config['API_KEY_OPERATOR']:
        return jsonify({'error': 'unauthorized'}), 401

    wallet = current_app.config["WALLET"]
    wallet.delete_transfers(None, None, False)
    return jsonify({}), 204


@bp.route('/fail', methods=['GET'])
def fail_transfers():
    """Fail currently pending transfers."""
    auth = request.headers.get('X-Api-Key')
    if auth != current_app.config['API_KEY_OPERATOR']:
        return jsonify({'error': 'unauthorized'}), 401

    online = current_app.config["ONLINE"]
    wallet = current_app.config["WALLET"]
    wallet.fail_transfers(online, None, None, False)
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
    wallet.refresh(online, None, [])
    asset_list = wallet.list_assets([])
    asset_ids = [a.asset_id for a in asset_list.nia + asset_list.cfa]
    transfers = []
    for asset_id in asset_ids:
        asset_transfers = wallet.list_transfers(asset_id)
        for transfer in asset_transfers:
            if transfer.status not in status_filter:
                continue
            tces = [{
                'endpoint': tce.endpoint,
                'protocol': tce.protocol.name,
                'used': tce.used
            } for tce in transfer.consignment_endpoints]
            transfers.append({
                'status': transfer.status.name,
                'amount': transfer.amount,
                'kind': transfer.kind.name,
                'txid': transfer.txid,
                'blinded_utxo': transfer.blinded_utxo,
                'consignment_endpoints': tces,
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
        wallet.refresh(online, asset_id, [])
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
    unspent_dict = utils.wallet.get_unspent_dict(wallet, online)
    return jsonify({'unspents': unspent_dict})
