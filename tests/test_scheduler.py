"""Tests for APIs."""

import time

from faucet_rgb import scheduler
from faucet_rgb.database import Request
from faucet_rgb.scheduler import send_next_batch
from faucet_rgb.utils import get_spare_available, get_spare_utxos
from faucet_rgb.utils.wallet import get_sha256_hex
from tests.utils import (
    USER_HEADERS,
    issue_single_asset_with_supply,
    prepare_assets,
    prepare_user_wallets,
    receive_asset,
    wait_sched_create_utxos,
    wait_sched_process_pending,
    witness,
)


def _app_prep_single_asset_false(app):
    """Prepare app to test SINGLE_ASSET_SEND set to False."""
    app = prepare_assets(app, "group_1")
    app = prepare_assets(app, "group_2")
    app.config["SINGLE_ASSET_SEND"] = False
    return app


def _app_prep_create_witness_utxos(app):
    """Prepare app to test UTXO creation for witness batch transfers."""
    app = prepare_assets(app, "group_1", issue_func=_issue_single_asset_1000, send_amount=1)
    return app


def _issue_single_asset_1000(app):
    return issue_single_asset_with_supply(app, 1000)


def test_create_spare_utxos(get_app):
    """Test UTXO creation."""
    app = get_app()
    client = app.test_client()

    scheduler.pause()

    # check initial state
    assert len(get_spare_utxos(app.config)) < app.config["SPARE_UTXO_THRESH"]

    # let the scheduler create new UTXOs
    scheduler.resume()
    wait_sched_create_utxos(app)

    # check new spare UTXO state
    assert len(get_spare_utxos(app.config)) == app.config["SPARE_UTXO_NUM"]

    # request enough witness assets to trigger UTXO creation
    num = app.config["SPARE_UTXO_NUM"] - app.config["SPARE_UTXO_THRESH"]
    for _ in range(num):
        user = prepare_user_wallets(app, 1)[0]
        invoice = witness(app.config, user)
        resp = receive_asset(client, user["xpub"], invoice)
        assert resp.status_code == 200
        wait_sched_process_pending(app)  # avoid batching

    scheduler.pause()

    # check UTXO state
    assert len(get_spare_utxos(app.config)) < app.config["SPARE_UTXO_THRESH"]

    # let the scheduler create new UTXOs
    scheduler.resume()
    wait_sched_create_utxos(app)

    # check new spare UTXO state
    assert len(get_spare_utxos(app.config)) == app.config["SPARE_UTXO_NUM"]


def test_create_witness_utxos(get_app):
    """Test UTXO creation."""
    app = get_app(_app_prep_create_witness_utxos)
    client = app.test_client()

    # check initial spare available
    spare_utxos = get_spare_utxos(app.config)
    available = get_spare_available(spare_utxos)
    print("available:", available)

    scheduler.pause()

    # accumulate enough witness requests for the same asset (for batching)
    num = round(available / app.config["UTXO_SIZE"]) + 1
    for _ in range(num):
        user = prepare_user_wallets(app, 1)[0]
        invoice = witness(app.config, user)
        resp = client.post(
            "/receive/asset",
            json={
                "wallet_id": get_sha256_hex(user["xpub"]),
                "invoice": invoice,
                "asset_group": "group_1",
            },
            headers=USER_HEADERS,
        )
        assert resp.status_code == 200

    scheduler.resume()

    # process requests in batch
    wait_sched_process_pending(app)

    # wait for all requets to have been served
    with app.app_context():
        request_num = Request.query.count()
        while Request.query.filter_by(status=40).count() != request_num:
            time.sleep(2)


def test_single_asset_false(get_app):
    """Test UTXO creation."""
    app = get_app(_app_prep_single_asset_false)
    client = app.test_client()

    scheduler.pause()

    users = prepare_user_wallets(app, 2)

    # request 2 different assets
    for idx, user in enumerate(users):
        invoice = witness(app.config, user)
        resp = client.post(
            "/receive/asset",
            json={
                "wallet_id": get_sha256_hex(user["xpub"]),
                "invoice": invoice,
                "asset_group": f"group_{idx+1}",
            },
            headers=USER_HEADERS,
        )
        assert resp.status_code == 200

    with app.app_context():
        assert Request.query.count() == 2
        assert all(r.status == 20 for r in Request.query.all())

    # manually trigger the sending function once
    send_next_batch(get_spare_utxos(app.config))

    # check both assets have been sent (in a single batch)
    with app.app_context():
        assert Request.query.count() == 2
        assert all(r.status == 40 for r in Request.query.all())
