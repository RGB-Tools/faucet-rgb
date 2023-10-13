"""Tests for random distribution mode."""

import time
from datetime import datetime, timedelta, timezone

from faucet_rgb import Request
from faucet_rgb.utils.wallet import get_sha256_hex
from tests.utils import (
    OPERATOR_HEADERS, USER_HEADERS, create_and_blind, prepare_assets,
    prepare_user_wallets, random_dist_mode, receive_asset,
    wait_sched_process_pending, wait_sched_process_waiting)


def _app_preparation_random(app):
    """Prepare app for the first launch."""
    now = datetime.now(timezone.utc)
    req_win_open = now + timedelta(seconds=30)
    dist_mode = random_dist_mode(app.config, now + timedelta(seconds=30),
                                 req_win_open + timedelta(minutes=1))
    app = prepare_assets(app,
                         "group_1",
                         dist_mode=dist_mode,
                         issue_func=_issue_asset_for_random,
                         send_amount=1)
    return app


def _issue_asset_for_random(app):
    """Issue 1 CFA asset with faucet-rgb's wallet.

    Returns a list with its asset ID, for compatibility with _issue_asset.
    """
    wallet = app.config["WALLET"]
    online = app.config["ONLINE"]
    wallet.create_utxos(online, True, None, app.config['UTXO_SIZE'],
                        app.config["FEE_RATE"])
    cfa = wallet.issue_asset_cfa(
        online,
        name="test random CFA distribution",
        description="a CFA asset for testing random distribution",
        precision=0,
        amounts=[2],
        file_path=None,
    )
    return [cfa.asset_id]


def test_random(get_app):
    """Test random distribtion mode."""
    app = get_app(_app_preparation_random)
    client = app.test_client()

    asset_balance = 2
    extra_requests = 1

    dist_conf = app.config['ASSETS']['group_1']['distribution']
    req_win = {
        'open':
        datetime.strptime(dist_conf['params']['request_window_open'],
                          app.config['DATE_FORMAT']),
        'close':
        datetime.strptime(dist_conf['params']['request_window_close'],
                          app.config['DATE_FORMAT'])
    }

    # check asset has future balance 2
    res = client.get('/control/assets', headers=OPERATOR_HEADERS)
    assert res.status_code == 200
    assert len(res.json['assets']) == 1
    asset = next(iter(res.json['assets']))
    assert res.json['assets'][asset]['balance']['future'] == asset_balance

    users = prepare_user_wallets(app, asset_balance + extra_requests)

    # check cannot request before window open + wait window open
    assert datetime.now(timezone.utc) < req_win['open']

    resp = client.post(
        "/receive/asset",
        json={
            'wallet_id': get_sha256_hex(users[0]["xpub"]),
            'invoice': create_and_blind(app.config, users[0]),
        },
        headers=USER_HEADERS,
    )
    assert resp.status_code == 403

    # wait for window open
    print('waiting for random request window to open...')
    while datetime.now(timezone.utc) < req_win['open']:
        time.sleep(5)
    print('random request window opened')

    # place 3 requests
    for user in users:
        resp = receive_asset(client, user["xpub"],
                             create_and_blind(app.config, user))
        assert resp.status_code == 200

    # check requests are in waiting status (while window is still open)
    with app.app_context():
        assert Request.query.filter_by(
            status=25).count() == asset_balance + extra_requests

    # wait for window close
    print('waiting for random request window to close...')
    while datetime.now(timezone.utc) < req_win['close']:
        time.sleep(5)
    print('random request window closed')

    # wait for scheduler job to process requests
    wait_sched_process_waiting(app)
    wait_sched_process_pending(app)
    time.sleep(5)  # give the scheduler time to complete the send

    # check requests have been moved to served or unmet status
    with app.app_context():
        # <asset_balance> requests expected in status served
        assert Request.query.filter_by(status=40).count() == asset_balance
        # <extra_requests> requests expected in status unmet (not selected)
        assert Request.query.filter_by(status=45).count() == extra_requests

    # check 1 asset has been received by the user of each chosen request
    result = {
        'served': 0,
        'unmet': 0,
    }
    for user in users:
        user['wallet'].refresh(user['online'], None, [])
        assets = user['wallet'].list_assets([])
        if assets.cfa:
            result['served'] += 1
        else:
            result['unmet'] += 1
    assert result['served'] == asset_balance
    assert result['unmet'] == extra_requests
