"""Faucet blueprint to top-up funds."""

import random

from flask import Blueprint, current_app, jsonify, request

from .database import Request, db
from .utils import get_current_timestamp, get_logger, get_rgb_asset
from .utils.wallet import is_xpub_valid

bp = Blueprint('receive', __name__, url_prefix='/receive')


@bp.route('/requests', methods=['GET'])
def list_requests():
    """Return requests.

    Max 100 requests are returned.
    Request can include filters as query parameters:
    - 'status' (default 20)
    - 'asset_group'
    - 'asset_id'
    - 'blinded_utxo'
    - 'wallet_id'
    """
    auth = request.headers.get('X-Api-Key')
    if auth != current_app.config['API_KEY_OPERATOR']:
        return jsonify({'error': 'unauthorized'}), 401

    status = 20
    if request.args.get('status') is not None:
        status = status = request.args.get('status')
    reqs = Request.query.filter_by(status=status)
    if request.args.get('asset_group') is not None:
        reqs = reqs.filter_by(asset_group=request.args.get('asset_group'))
    if request.args.get('asset_id') is not None:
        reqs = reqs.filter_by(asset_id=request.args.get('asset_id'))
    if request.args.get('blinded_utxo') is not None:
        reqs = reqs.filter_by(blinded_utxo=request.args.get('blinded_utxo'))
    if request.args.get('wallet_id') is not None:
        reqs = reqs.filter_by(wallet_id=request.args.get('wallet_id'))

    requests = []
    for req in reqs.order_by(Request.idx.desc()).slice(0, 100).all():
        requests.append({
            'idx': req.idx,
            'timestamp': req.timestamp,
            'status': req.status,
            'wallet_id': req.wallet_id,
            'blinded_utxo': req.blinded_utxo,
            'asset_group': req.asset_group,
            'asset_id': req.asset_id,
            'amount': req.amount,
        })

    return jsonify({'requests': requests})


@bp.route('/config/<wallet_id>', methods=['GET'])
def config(wallet_id):
    """Return current faucet configuration.

    wallet_id must be a valid XPub

    returns:
    - faucet name
    - configured groups and for each one:
      - its label
      - how many requests to /receive/asset the given wallet_id has left
    """
    auth = request.headers.get('X-Api-Key')
    if auth != current_app.config['API_KEY']:
        return jsonify({'error': 'unauthorized'}), 401

    # check wallet_id is a valid XPub
    if not is_xpub_valid(wallet_id):
        return jsonify({'error': 'invalied wallet ID'}), 403

    # drop requests in status "new" which are older than a couple minutes
    time_thresh = get_current_timestamp() - 120
    Request.query.filter(Request.status == 10,
                         Request.timestamp < time_thresh).delete()
    db.session.commit()  # pylint: disable=no-member

    assets = current_app.config["ASSETS"]
    groups = {}
    for group_name, group_data in assets.items():
        reqs = Request.query.filter(Request.wallet_id == wallet_id,
                                    Request.asset_group == group_name).count()
        requests_left = 1 if not reqs else 0
        groups[group_name] = {
            'label': group_data['label'],
            'requests_left': requests_left,
        }
    return jsonify({'name': current_app.config["NAME"], 'groups': groups})


@bp.route('/asset/<wallet_id>/<blinded_utxo>', methods=['GET'])
def request_rgb_asset(wallet_id, blinded_utxo):
    """Request sending configured amount to the provided blinded UTXO.

    - wallet_id must be a valid XPub
    - an optional asset_group can be requested via query parameter
    - a wallet_id cannot request from the same asset group more than once
    - each request is checked before saving to db to make sure it can be sent
    - valid requests are saved, processing is tried immediately in a thread
    """
    logger = get_logger(__name__)
    auth = request.headers.get('X-Api-Key')
    if auth != current_app.config['API_KEY']:
        return jsonify({'error': 'unauthorized'}), 401

    # check wallet_id is a valid XPub
    if not is_xpub_valid(wallet_id):
        return jsonify({'error': 'invalied wallet ID'}), 403

    # choose asset group
    configured_assets = current_app.config["ASSETS"]
    asset_group = request.args.get('asset_group')
    if asset_group is not None:
        if asset_group not in configured_assets:
            return jsonify({'error': 'Invalid asset group'}), 404
    else:
        asset_group = random.choice(list(configured_assets))
    asset = random.choice(list(configured_assets[asset_group]['assets']))

    # max 1 request per asset group per wallet ID
    reqs = Request.query.filter(Request.wallet_id == wallet_id,
                                Request.asset_group == asset_group).count()
    if reqs:
        logger.debug('wallet %s already requested from group %s', wallet_id,
                     asset_group)
        return jsonify({
            'error':
            'asset donation from this group has already been requested'
        }), 403

    # add request to db so max requests check works right away (no double req)
    # pylint: disable=no-member
    db.session.add(Request(wallet_id, blinded_utxo, asset_group, None, None))
    req = Request.query.filter(Request.wallet_id == wallet_id,
                               Request.blinded_utxo == blinded_utxo,
                               Request.asset_group == asset_group,
                               Request.status == 10)
    assert req.count() == 1
    req_idx = req.first().idx
    db.session.commit()
    # pylint: enable=no-member

    # prepare asset data
    rgb_asset, schema = get_rgb_asset(asset['asset_id'])
    if rgb_asset is None:
        return jsonify({'error': 'Internal error getting asset data'}), 500
    asset_data = {
        'asset_id': asset['asset_id'],
        'schema': schema,
        'amount': asset['amount'],
        'name': rgb_asset.name,
        'precision': rgb_asset.precision,
        'description': None,
        'parent_id': None,
        'ticker': None,
    }
    if hasattr(rgb_asset, 'description'):
        asset_data['description'] = rgb_asset.description
    if hasattr(rgb_asset, 'parent_id'):
        asset_data['parent_id'] = rgb_asset.parent_id
    if hasattr(rgb_asset, 'ticker'):
        asset_data['ticker'] = rgb_asset.ticker

    # update request on db: update status, set asset_id and amount
    # pylint: disable=no-member
    logger.debug('setting request %s: asset_id %s, amount %s', req_idx,
                 asset["asset_id"], asset["amount"])
    Request.query.filter_by(idx=req_idx).update({
        "status": 20,
        "asset_id": asset['asset_id'],
        "amount": asset['amount']
    })
    db.session.commit()
    # pylint: enable=no-member

    return jsonify({'asset': asset_data})
