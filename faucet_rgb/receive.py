"""Faucet blueprint to top-up funds."""

import random
from datetime import datetime, timezone

from flask import Blueprint, current_app, jsonify, request

from faucet_rgb.settings import DistributionMode

from .database import Request, db
from .utils import get_current_timestamp, get_logger, get_rgb_asset
from .utils.wallet import is_walletid_valid

bp = Blueprint('receive', __name__, url_prefix='/receive')


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

    # check wallet_id is valid
    if not is_walletid_valid(wallet_id):
        return jsonify({'error': 'invalied wallet ID'}), 403

    # drop requests in status "new" which are older than a couple minutes
    time_thresh = get_current_timestamp() - 120
    Request.query.filter(Request.status == 10, Request.timestamp
                         < time_thresh).delete()
    db.session.commit()  # pylint: disable=no-member

    assets = current_app.config["ASSETS"]
    groups = {}
    for group_name, group_data in assets.items():
        allowed = _is_request_allowed(wallet_id, group_name)
        groups[group_name] = {
            'label': group_data['label'],
            'requests_left': 1 if allowed else 0,
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

    # check wallet_id is valid
    if not is_walletid_valid(wallet_id):
        return jsonify({'error': 'invalid wallet ID'}), 403

    # choose asset group
    configured_assets = current_app.config["ASSETS"]
    asset_group = request.args.get('asset_group')
    if asset_group is not None:
        if asset_group not in configured_assets:
            return jsonify({'error': 'Invalid asset group'}), 404
    asset = None
    if asset_group is None:
        # chose randomly from non-migration groups
        asset_group = random.choice(
            list(current_app.config['NON_MIGRATION_GROUPS']))
    asset = random.choice(list(configured_assets[asset_group]['assets']))

    # check if request is allowed
    allowed = _is_request_allowed(wallet_id, asset_group)
    if not allowed:
        return jsonify({
            'error':
            f'wallet has no right to request an asset from group {asset_group}'
        }), 403

    # handle asset migration
    non_mig_groups = current_app.config['NON_MIGRATION_GROUPS']
    is_mig_request = asset_group not in non_mig_groups
    if is_mig_request:
        # wallet is entitled to a migration > detect the asset to be sent
        mig_cache = current_app.config['ASSET_MIGRATION_CACHE']
        asset = mig_cache[asset_group].get(wallet_id)
        # remove the user (and possibly the whole group) from migration cache
        del mig_cache[asset_group][wallet_id]
        if not mig_cache[asset_group]:
            del mig_cache[asset_group]

    return _request_rgb_asset_core(wallet_id, blinded_utxo, asset_group, asset,
                                   logger)


def _request_rgb_asset_core(wallet_id, blinded_utxo, asset_group, asset,
                            logger):

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
    new_status = 20
    dist_conf = current_app.config['ASSETS'][asset_group]['distribution']
    dist_mode = DistributionMode(dist_conf['mode'])
    if dist_mode == DistributionMode.RANDOM:
        new_status = 25
    # pylint: disable=no-member
    logger.debug('setting request %s: asset_id %s, amount %s, status %s',
                 req_idx, asset["asset_id"], asset["amount"], new_status)
    Request.query.filter_by(idx=req_idx).update({
        "status": new_status,
        "asset_id": asset['asset_id'],
        "amount": asset['amount']
    })
    db.session.commit()
    # pylint: enable=no-member

    return jsonify({'asset': asset_data})


def _is_request_allowed(wallet_id, group_name):
    """Return if a request should be allowed or denied."""
    # deny request if user has already placed a request for this group
    reqs = Request.query.filter(Request.wallet_id == wallet_id,
                                Request.asset_group == group_name).count()
    if reqs:
        return False

    # deny based on distribution mode
    dist_conf = current_app.config['ASSETS'][group_name]['distribution']
    dist_mode = DistributionMode(dist_conf['mode'])
    if dist_mode == DistributionMode.RANDOM:
        req_win_open = dist_conf['params']['request_window_open']
        req_win_close = dist_conf['params']['request_window_close']
        date_format = current_app.config['DATE_FORMAT']
        req_win_open = datetime.strptime(req_win_open, date_format)
        req_win_close = datetime.strptime(req_win_close, date_format)
        now = datetime.now(timezone.utc)
        # deny requests outside the configured request window
        if now < req_win_open or now > req_win_close:
            return False

    # deny based on migration configuration and status
    if group_name not in current_app.config['NON_MIGRATION_GROUPS']:
        mig_cache_group = current_app.config['ASSET_MIGRATION_CACHE'].get(
            group_name)
        # no requests allowed for completely migrated groups
        if mig_cache_group is None:
            return False
        # deny request if wallet ID is not in migration group
        if mig_cache_group.get(wallet_id) is None:
            return False

    # allow request
    return True
