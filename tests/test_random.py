"""Tests for random distribution mode."""

import time
from datetime import datetime, timedelta

from faucet_rgb import Request
from faucet_rgb.receive import REASON_MAP
from faucet_rgb.settings import DistributionMode
from faucet_rgb.utils.wallet import get_sha256_hex
from tests.utils import (
    OPERATOR_HEADERS,
    USER_HEADERS,
    create_and_blind,
    issue_single_asset_with_supply,
    prepare_assets,
    prepare_user_wallets,
    random_dist_mode,
    receive_asset,
    req_win_datetimes,
    wait_sched_process_pending,
    wait_sched_process_waiting,
)


def _app_prep_random_single_asset(app):
    """Prepare app to test random distribution."""
    now = datetime.now()
    req_win_open = now + timedelta(seconds=30)
    dist_mode = random_dist_mode(app.config, req_win_open, req_win_open + timedelta(minutes=1))
    app = prepare_assets(
        app,
        "group_1",
        dist_mode=dist_mode,
        issue_func=_issue_single_asset_2,
        send_amount=1,
    )
    return app


def _app_prep_random_multiple_assets(app):
    """Prepare app to test random distribution."""
    now = datetime.now()
    req_win_open = now
    dist_mode = random_dist_mode(app.config, req_win_open, req_win_open + timedelta(minutes=1))
    app = prepare_assets(
        app,
        "group_1",
        dist_mode=dist_mode,
        issue_func=_issue_multiple_assets_2,
        send_amount=1,
    )
    return app


def _issue_single_asset_2(app):
    return issue_single_asset_with_supply(app, 2)


def _issue_multiple_assets_2(app):
    """Issue 2 CFA assets with supply 2 each with faucet-rgb's wallet.

    Returns a list with its asset ID, for compatibility with _issue_asset.
    """
    supply = 2
    wallet = app.config["WALLET"]
    online = app.config["ONLINE"]
    wallet.create_utxos(online, True, None, app.config["UTXO_SIZE"], app.config["FEE_RATE"])
    cfa_1 = wallet.issue_asset_cfa(
        online,
        name="test with multiple CFA assets 1",
        description="CFA asset for testing 1",
        precision=0,
        amounts=[supply],
        file_path=None,
    )
    cfa_2 = wallet.issue_asset_cfa(
        online,
        name="test with multiple CFA assets 2",
        description="CFA asset for testing 2",
        precision=0,
        amounts=[supply],
        file_path=None,
    )
    return [cfa_1.asset_id, cfa_2.asset_id]


def test_random_single_asset(get_app):
    """Test random distribtion mode with asingle asset."""
    app = get_app(_app_prep_random_single_asset)
    client = app.test_client()

    asset_balance = 2
    extra_requests = 1

    dist_conf = app.config["ASSETS"]["group_1"]["distribution"]
    req_win = req_win_datetimes(dist_conf, app.config["DATE_FORMAT"])

    # check asset has future balance 2
    res = client.get("/control/assets", headers=OPERATOR_HEADERS)
    assert res.status_code == 200
    assert len(res.json["assets"]) == 1
    asset = next(iter(res.json["assets"]))
    assert res.json["assets"][asset]["balance"]["future"] == asset_balance

    users = prepare_user_wallets(app, asset_balance + extra_requests)

    # check cannot request before window open + wait window open
    assert datetime.now() < req_win["open"]

    resp = client.post(
        "/receive/asset",
        json={
            "wallet_id": get_sha256_hex(users[0]["xpub"]),
            "invoice": create_and_blind(app.config, users[0]),
        },
        headers=USER_HEADERS,
    )
    assert resp.status_code == 403
    assert resp.json["reason"] == REASON_MAP[2]

    # wait for window open
    print("waiting for random request window to open...")
    while datetime.now() < req_win["open"]:
        time.sleep(5)
    print("random request window opened")

    # place requests
    for user in users:
        resp = receive_asset(client, user["xpub"], create_and_blind(app.config, user))
        assert resp.status_code == 200
    assert resp.json["distribution"]["mode"] == DistributionMode.RANDOM.value

    # check requests are in waiting status (while window is still open)
    with app.app_context():
        assert Request.query.filter_by(status=25).count() == asset_balance + extra_requests

    # wait for window close
    print("waiting for random request window to close...")
    while datetime.now() < req_win["close"]:
        time.sleep(5)
    print("random request window closed")

    # check cannot request after window close
    user = prepare_user_wallets(app, 1, start_num=len(users))[0]
    resp = client.post(
        "/receive/asset",
        json={
            "wallet_id": get_sha256_hex(user["xpub"]),
            "invoice": create_and_blind(app.config, user),
        },
        headers=USER_HEADERS,
    )
    assert resp.status_code == 403
    assert resp.json["reason"] == REASON_MAP[2]

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
        "served": 0,
        "unmet": 0,
    }
    for user in users:
        user["wallet"].refresh(user["online"], None, [])
        assets = user["wallet"].list_assets([])
        if assets.cfa:
            assert len(assets.cfa) == 1  # only one asset sent to each user
            result["served"] += 1
        else:
            result["unmet"] += 1
    assert result["served"] == asset_balance
    assert result["unmet"] == extra_requests


def test_random_multiple_assets(get_app):  # pylint: disable=too-many-locals
    """Test random distribtion mode with multiple assets."""
    app = get_app(_app_prep_random_multiple_assets)
    client = app.test_client()

    asset_balance = 2
    extra_requests = 1
    request_num = (asset_balance + extra_requests) * 2

    dist_conf = app.config["ASSETS"]["group_1"]["distribution"]
    req_win = {
        "open": datetime.strptime(
            dist_conf["random_params"]["request_window_open"], app.config["DATE_FORMAT"]
        ),
        "close": datetime.strptime(
            dist_conf["random_params"]["request_window_close"],
            app.config["DATE_FORMAT"],
        ),
    }

    # check assets hves future balance 2
    res = client.get("/control/assets", headers=OPERATOR_HEADERS)
    assert res.status_code == 200
    assert len(res.json["assets"]) == 2
    for asset in iter(res.json["assets"]):
        assert res.json["assets"][asset]["balance"]["future"] == asset_balance

    users = prepare_user_wallets(app, request_num)

    # place requests
    for user in users:
        resp = receive_asset(client, user["xpub"], create_and_blind(app.config, user))
        assert resp.status_code == 200

    # check requests are in waiting status (while window is still open)
    with app.app_context():
        assert Request.query.filter_by(status=25).count() == request_num

    # wait for window close
    print("waiting for random request window to close...")
    while datetime.now() < req_win["close"]:
        time.sleep(5)
    print("random request window closed")

    # wait for scheduler job to process requests
    wait_sched_process_waiting(app)
    wait_sched_process_pending(app)
    time.sleep(5)  # give the scheduler time to complete the send

    # wait for requests to have moved to served or unmet status
    with app.app_context():
        deadline = time.time() + 30
        while True:
            time.sleep(2)
            # <asset_balance> requests expected in status served
            # <extra_requests> requests expected in status unmet (not selected)
            served = Request.query.filter_by(status=40).count()
            unmet = Request.query.filter_by(status=45).count()
            if served == asset_balance * 2 and unmet == extra_requests * 2:
                break
            if time.time() > deadline:
                raise RuntimeError("requests not getting served or unmet as expected")

    # check 1 asset has been received by the user of each chosen request
    result = {
        "served": 0,
        "unmet": 0,
    }
    for user in users:
        user["wallet"].refresh(user["online"], None, [])
        assets = user["wallet"].list_assets([])
        if assets.cfa:
            result["served"] += 1
        else:
            result["unmet"] += 1
    assert result["served"] == asset_balance * 2
    assert result["unmet"] == extra_requests * 2
