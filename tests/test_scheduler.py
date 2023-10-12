"""Tests for APIs."""

from faucet_rgb import scheduler
from tests.utils import (
    get_spare_utxos, prepare_user_wallets, receive_asset,
    wait_sched_create_utxos, wait_sched_process_pending, witness)


def test_create_utxos(get_app):
    """Test UTXO creation."""
    app = get_app()
    client = app.test_client()

    scheduler.pause()

    # check initial state
    assert len(get_spare_utxos(app.config)) < app.config['SPARE_UTXO_THRESH']

    # let the scheduler create new UTXOs
    scheduler.resume()
    wait_sched_create_utxos(app)

    # check new spare UTXO state
    assert len(get_spare_utxos(app.config)) == app.config['SPARE_UTXO_NUM']

    # request enough witness assets to trigger UTXO creation
    num = app.config['SPARE_UTXO_NUM'] - app.config['SPARE_UTXO_THRESH']
    for _ in range(num):
        user = prepare_user_wallets(app, 1)[0]
        invoice = witness(app.config, user)
        resp = receive_asset(client, user["xpub"], invoice)
        assert resp.status_code == 200
        wait_sched_process_pending(app)  # avoid batching

    scheduler.pause()

    # check UTXO state
    assert len(get_spare_utxos(app.config)) < app.config['SPARE_UTXO_THRESH']

    # let the scheduler create new UTXOs
    scheduler.resume()
    wait_sched_create_utxos(app)

    # check new spare UTXO state
    assert len(get_spare_utxos(app.config)) == app.config['SPARE_UTXO_NUM']
