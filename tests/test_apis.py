"""Tests for APIs."""

import random
import time
import uuid
from datetime import datetime, timedelta

import rgb_lib

from faucet_rgb import Request, scheduler
from faucet_rgb.settings import DistributionMode
from faucet_rgb.utils.wallet import get_sha256_hex
from tests.utils import (
    BAD_HEADERS, ISSUE_AMOUNT, OPERATOR_HEADERS, SEND_AMOUNT, USER_HEADERS,
    add_fake_request, check_receive_asset, create_and_blind, generate,
    prepare_assets, prepare_user_wallets, random_dist_mode, receive_asset,
    refresh_and_check_settled, req_win_datetimes, wait_refresh,
    wait_sched_process_pending, wait_xfer_status, witness)


def _app_prep_mainnet(app):
    """Prepare app configured on the mainnet network."""
    app = prepare_assets(app, "group_1")
    app.config["NETWORK"] = 'mainnet'
    return app


def _app_prep_mainnet_witness_allowed(app):
    """Prepare app configured on the mainnet network with witness allowed."""
    app = prepare_assets(app, "group_1")
    app.config["NETWORK"] = 'mainnet'
    app.config["WITNESS_ALLOWED_NETWORKS"] = ['mainnet']
    return app


def _app_prep_random(app):
    """Prepare app to test random distribution."""
    now = datetime.now()
    req_win_open = now - timedelta(seconds=30)
    dist_mode = random_dist_mode(app.config, req_win_open,
                                 req_win_open + timedelta(minutes=1))
    app = prepare_assets(app, "group_1", dist_mode=dist_mode)
    return app


def test_control_assets(get_app):
    """Test /control/assets endpoint."""
    api = '/control/assets'
    app = get_app()
    client = app.test_client()

    # auth failure
    res = client.get(api, headers=USER_HEADERS)
    assert res.status_code == 401

    # success
    res = client.get(api, headers=OPERATOR_HEADERS)
    assert res.status_code == 200
    assert 'assets' in res.json
    assert len(res.json['assets']) == 2
    first_asset = next(iter(res.json['assets']))
    assert 'balance' in res.json['assets'][first_asset]
    assert 'name' in res.json['assets'][first_asset]
    assert 'precision' in res.json['assets'][first_asset]


def test_control_delete(get_app):
    """Test /control/delete endpoint."""
    api = '/control/delete'
    app = get_app()
    client = app.test_client()

    # auth failure
    res = client.get(api, headers=USER_HEADERS)
    assert res.status_code == 401

    asset_list = app.config['WALLET'].list_assets([])
    asset_id = asset_list.nia[0].asset_id

    # create a WAITING_COUNTERPARTY transfer + fail it
    _ = app.config['WALLET'].blind_receive(asset_id, None, 1,
                                           app.config["TRANSPORT_ENDPOINTS"],
                                           app.config["MIN_CONFIRMATIONS"])
    print('waiting for the transfer to expire...')
    time.sleep(2)
    resp = client.get(
        "/control/fail",
        headers=OPERATOR_HEADERS,
    )
    assert resp.status_code == 200
    assert resp.json['result'] is True
    asset_transfers = app.config['WALLET'].list_transfers(asset_id)
    transfers_failed = [
        t for t in asset_transfers if t.status == rgb_lib.TransferStatus.FAILED
    ]
    assert len(transfers_failed) == 1
    # delete the failed transfer
    resp = client.get(
        api,
        headers=OPERATOR_HEADERS,
    )
    assert resp.status_code == 200
    assert resp.json['result'] is True
    asset_transfers = app.config['WALLET'].list_transfers(asset_id)
    transfers_failed = [
        t for t in asset_transfers if t.status == rgb_lib.TransferStatus.FAILED
    ]
    assert len(transfers_failed) == 0


def test_control_fail(get_app):
    """Test /control/fail endpoint."""
    api = '/control/fail'
    app = get_app()
    client = app.test_client()

    # auth failure
    res = client.get(api, headers=USER_HEADERS)
    assert res.status_code == 401

    # return False is no transfer has changed
    resp = client.get(api, headers=OPERATOR_HEADERS)
    assert resp.status_code == 200
    assert resp.json['result'] is False

    asset_list = app.config['WALLET'].list_assets([])
    asset_id = asset_list.nia[0].asset_id

    # create a transfer in status WAITING_COUNTERPARTY with a 1s expiration
    _ = app.config['WALLET'].blind_receive(asset_id, None, 1,
                                           app.config["TRANSPORT_ENDPOINTS"],
                                           app.config["MIN_CONFIRMATIONS"])
    print('waiting for the transfer to expire...')
    time.sleep(2)
    asset_transfers = app.config['WALLET'].list_transfers(asset_id)
    transfers_wait_counterparty = [
        t for t in asset_transfers
        if t.status == rgb_lib.TransferStatus.WAITING_COUNTERPARTY
    ]
    assert len(transfers_wait_counterparty) == 1
    # fail the transfer
    resp = client.get(
        api,
        headers=OPERATOR_HEADERS,
    )
    assert resp.status_code == 200
    assert resp.json['result'] is True
    asset_transfers = app.config['WALLET'].list_transfers(asset_id)
    transfers_wait_counterparty = [
        t for t in asset_transfers
        if t.status == rgb_lib.TransferStatus.WAITING_COUNTERPARTY
    ]
    assert not transfers_wait_counterparty
    transfers_failed = [
        t for t in asset_transfers if t.status == rgb_lib.TransferStatus.FAILED
    ]
    assert len(transfers_failed) == 1


def test_control_refresh(get_app):
    """Test /control/refresh/<asset_id> endpoint."""
    api = '/control/refresh'
    app = get_app()
    client = app.test_client()

    # auth failure
    res = client.get(f"{api}/assetid", headers=USER_HEADERS)
    assert res.status_code == 401

    # bad asset ID
    resp = client.get(
        f"{api}/invalid",
        headers=OPERATOR_HEADERS,
    )
    assert resp.status_code == 404
    assert 'unknown asset ID' in resp.json['error']

    # transfer refresh
    user = prepare_user_wallets(app, 1)[0]
    check_receive_asset(app, user, None, 200)
    with app.app_context():
        request = Request.query.one()
    asset_id = request.asset_id
    wait_sched_process_pending(app)
    resp = client.get(
        f"{api}/{asset_id}",
        headers=OPERATOR_HEADERS,
    )
    assert resp.status_code == 200
    assert resp.json['result'] is False
    asset_transfers = app.config['WALLET'].list_transfers(asset_id)
    transfer = [
        t for t in asset_transfers if t.kind == rgb_lib.TransferKind.SEND
    ][0]
    assert transfer.status == rgb_lib.TransferStatus.WAITING_CONFIRMATIONS
    # mine a block + refresh the transfer + check it's now settled
    generate(1)
    refresh_and_check_settled(client, app.config, asset_id)


def test_control_requests(get_app):  # pylint: disable=too-many-statements
    """Test /control/requests endpoint."""
    api = '/control/requests'
    app = get_app()
    client = app.test_client()

    # auth failure
    res = client.get(api, headers=USER_HEADERS)
    assert res.status_code == 401

    # no requests
    resp = client.get(
        api,
        headers=OPERATOR_HEADERS,
    )
    assert resp.status_code == 200
    assert not resp.json['requests']

    users = prepare_user_wallets(app, 2)
    scheduler.pause()
    add_fake_request(app,
                     users[0],
                     'group_1',
                     20,
                     amount=1,
                     asset_id=uuid.uuid4().hex,
                     hash_wallet_id=True)
    add_fake_request(app,
                     users[1],
                     'group_2',
                     20,
                     amount=2,
                     asset_id=uuid.uuid4().hex,
                     hash_wallet_id=True)
    add_fake_request(app,
                     users[0],
                     'group_1',
                     40,
                     amount=3,
                     asset_id=uuid.uuid4().hex)

    with app.app_context():
        all_reqs = Request.query.all()

    # requests in status 20 (default)
    resp_default = client.get(
        api,
        headers=OPERATOR_HEADERS,
    )
    assert resp_default.status_code == 200
    status = 20
    resp = client.get(
        f"{api}?status={status}",
        headers=OPERATOR_HEADERS,
    )
    assert resp.status_code == 200
    assert resp_default.json == resp.json
    assert len(resp.json['requests']) == 2
    assert all(r.get('status') == status for r in resp.json['requests'])
    assert any(r.get('amount') == 1 for r in resp.json['requests'])
    assert any(r.get('amount') == 2 for r in resp.json['requests'])

    # filter by status
    status = 40
    resp = client.get(
        f"{api}?status={status}",
        headers=OPERATOR_HEADERS,
    )
    assert resp.status_code == 200
    assert len(resp.json['requests']) == 1
    request = next(iter(resp.json['requests']))
    assert request['status'] == status
    assert request['amount'] == 3

    # filter by asset group
    asset_group = 'group_1'
    resp = client.get(
        f"{api}?asset_group={asset_group}",
        headers=OPERATOR_HEADERS,
    )
    assert resp.status_code == 200
    assert len(resp.json['requests']) == 2
    assert all(
        r.get('asset_group') == asset_group for r in resp.json['requests'])

    # filter by asset ID
    req = random.choice(all_reqs)
    resp = client.get(
        f"{api}?asset_id={req.asset_id}",
        headers=OPERATOR_HEADERS,
    )
    assert resp.status_code == 200
    assert len(resp.json['requests']) == 1
    assert all(
        r.get('asset_id') == req.asset_id for r in resp.json['requests'])
    assert all(r.get('amount') == req.amount for r in resp.json['requests'])

    # filter by recipient ID
    req = random.choice(all_reqs)
    resp = client.get(
        f"{api}?recipient_id={req.recipient_id}",
        headers=OPERATOR_HEADERS,
    )
    assert resp.status_code == 200
    assert len(resp.json['requests']) == 1
    assert all(
        r.get('recipient_id') == req.recipient_id
        for r in resp.json['requests'])
    assert all(r.get('amount') == req.amount for r in resp.json['requests'])

    # filter by wallet ID
    req = random.choice(all_reqs)
    resp = client.get(
        f"{api}?wallet_id={req.wallet_id}",
        headers=OPERATOR_HEADERS,
    )
    assert resp.status_code == 200
    assert len(resp.json['requests']) == 1
    assert all(
        r.get('wallet_id') == req.wallet_id for r in resp.json['requests'])
    assert all(r.get('amount') == req.amount for r in resp.json['requests'])

    # filter by asset group + status
    asset_group = 'group_1'
    status = 20
    resp = client.get(
        f"{api}?asset_group={asset_group}&status={status}",
        headers=OPERATOR_HEADERS,
    )
    assert resp.status_code == 200
    assert len(resp.json['requests']) == 1
    request = next(iter(resp.json['requests']))
    assert request['asset_group'] == asset_group
    assert request['status'] == status
    assert request['amount'] == 1


def test_control_transfers(get_app):  # pylint: disable=too-many-statements
    """Test /control/transfers endpoint."""
    api = '/control/transfers'
    app = get_app()
    client = app.test_client()

    # auth failure
    res = client.get(api, headers=USER_HEADERS)
    assert res.status_code == 401

    # 0 pending (WAITING_COUNTERPARTY + WAITING_CONFIRMATIONS) transfers
    resp = client.get(
        api,
        headers=OPERATOR_HEADERS,
    )
    assert resp.status_code == 200
    assert not resp.json['transfers']

    # 2 SETTLED transfer (issuances)
    resp = client.get(
        f"{api}?status=SETTLED",
        headers=OPERATOR_HEADERS,
    )
    assert resp.status_code == 200
    assert len(resp.json['transfers']) == 2
    for transfer in iter(resp.json['transfers']):
        assert transfer['kind'] == 'ISSUANCE'
        assert transfer['status'] == 'SETTLED'

    # 1 pending (WAITING_COUNTERPARTY + WAITING_CONFIRMATIONS) transfers
    user = prepare_user_wallets(app, 1)[0]
    check_receive_asset(app, user, None, 200)
    wait_sched_process_pending(app)
    resp = client.get(
        api,
        headers=OPERATOR_HEADERS,
    )
    assert resp.status_code == 200
    assert len(resp.json['transfers']) == 1
    transfer = next(iter(resp.json['transfers']))
    assert 'amount' in transfer
    assert 'kind' in transfer
    assert transfer['kind'] == 'SEND'
    assert 'recipient_id' in transfer
    assert transfer['status'] == 'WAITING_CONFIRMATIONS'
    assert 'txid' in transfer
    assert len(transfer['transfer_transport_endpoints']) == 1
    tte = next(iter(transfer['transfer_transport_endpoints']))
    assert 'endpoint' in tte
    assert tte['transport_type'] == 'JSON_RPC'
    assert tte['used'] is True

    # 0 WAITING_COUNTERPARTY transfers
    resp = client.get(
        f"{api}?status=WAITING_COUNTERPARTY",
        headers=OPERATOR_HEADERS,
    )
    assert resp.status_code == 200
    assert not resp.json['transfers']

    # 0 FAILED transfers
    resp = client.get(
        f"{api}?status=FAILED",
        headers=OPERATOR_HEADERS,
    )
    assert resp.status_code == 200
    assert not resp.json['transfers']

    asset_list = app.config['WALLET'].list_assets([])
    asset_id = asset_list.nia[0].asset_id

    # 1 WAITING_COUNTERPARTY transfer
    _ = app.config['WALLET'].blind_receive(asset_id, None, 1,
                                           app.config["TRANSPORT_ENDPOINTS"],
                                           app.config["MIN_CONFIRMATIONS"])
    print('waiting for the transfer to expire...')
    time.sleep(2)
    resp = client.get(
        f"{api}?status=WAITING_COUNTERPARTY",
        headers=OPERATOR_HEADERS,
    )
    assert resp.status_code == 200
    assert len(resp.json['transfers']) == 1

    # 1 FAILED transfer
    resp = client.get(
        "/control/fail",
        headers=OPERATOR_HEADERS,
    )
    assert resp.status_code == 200
    assert resp.json['result'] is True
    resp = client.get(
        f"{api}?status=FAILED",
        headers=OPERATOR_HEADERS,
    )
    assert resp.status_code == 200
    assert len(resp.json['transfers']) == 1


def test_control_unspents(get_app):
    """Test /control/unspents endpoint."""
    api = '/control/unspents'
    app = get_app()
    client = app.test_client()

    # auth failure
    res = client.get(api, headers=USER_HEADERS)
    assert res.status_code == 401

    resp = client.get(
        api,
        headers=OPERATOR_HEADERS,
    )
    assert resp.status_code == 200
    unspents = resp.json['unspents']
    assert len(unspents) == 6
    colorable = [u for u in unspents if u['utxo']['colorable']]
    vanilla = [u for u in unspents if not u['utxo']['colorable']]
    assert len(colorable) == 5
    assert len(vanilla) == 1
    for unspent in unspents:
        assert 'btc_amount' in unspent['utxo']
        assert 'colorable' in unspent['utxo']
        assert 'txid' in unspent['utxo']['outpoint']
        assert 'vout' in unspent['utxo']['outpoint']
        if unspent['rgb_allocations']:
            allocation = next(iter(unspent['rgb_allocations']))
            assert allocation['amount'] == ISSUE_AMOUNT
            assert 'asset_id' in allocation
            assert allocation['settled'] is True


def test_receive_asset(get_app):
    """Test /receive/asset endpoint."""
    api = '/receive/asset'
    app = get_app()
    client = app.test_client()

    user = prepare_user_wallets(app, 1)[0]
    wallet_id = get_sha256_hex(user["xpub"])

    # auth failure
    res = client.post(api, headers=BAD_HEADERS)
    assert res.status_code == 401
    # no body
    res = client.post(api, headers=USER_HEADERS)
    assert res.status_code == 400
    # malformed body (no wallet ID)
    res = client.post(api, json={'bad': 'data'}, headers=USER_HEADERS)
    assert res.status_code == 403
    # malformed body (no invoice)
    res = client.post(api, json={'wallet_id': wallet_id}, headers=USER_HEADERS)
    assert res.status_code == 403

    # check requests with xPub as wallet ID are denied
    resp = client.post(
        api,
        json={
            'wallet_id': user["xpub"],
            'invoice': create_and_blind(app.config, user),
        },
        headers=USER_HEADERS,
    )
    assert resp.status_code == 403

    # standard request
    scheduler.pause()
    resp = receive_asset(client, user["xpub"],
                         create_and_blind(app.config, user))
    assert resp.status_code == 200
    asset = resp.json["asset"]
    with app.app_context():
        request = Request.query.one()
    assert request.status == 20
    asset_id = request.asset_id
    assert asset["asset_id"] == asset_id
    assert 'amount' in asset
    assert 'name' in asset
    assert 'precision' in asset
    assert 'schema' in asset
    assert resp.json['distribution']['mode'] == DistributionMode.STANDARD.value

    scheduler.resume()
    wait_sched_process_pending(app)
    time.sleep(5)  # give the scheduler time to complete the send
    generate(1)
    wait_refresh(app.config['WALLET'], app.config['ONLINE'])
    with app.app_context():
        request = Request.query.filter_by(idx=request.idx).one()
    assert request.status == 40

    # request from an inexistent asset_group
    resp = client.post(
        api,
        json={
            'wallet_id': wallet_id,
            'invoice': create_and_blind(app.config, user),
            'asset_group': 'inexistent'
        },
        headers=USER_HEADERS,
    )
    assert resp.status_code == 404
    assert resp.json['error'] == 'invalid asset group'


def test_receive_asset_witness(get_app):
    """Test /receive/asset endpoint with a witness transfer."""
    app = get_app()
    client = app.test_client()

    user = prepare_user_wallets(app, 1)[0]

    # prepare 2 colorable UTXOs: 1 for BTC input (witness) + 1 for RGB change
    app.config['WALLET'].create_utxos(app.config['ONLINE'], True, 2,
                                      app.config['UTXO_SIZE'],
                                      app.config['FEE_RATE'])

    # request using a witness tx invoice
    invoice = witness(app.config, user)
    resp = receive_asset(client, user["xpub"], invoice)
    assert resp.status_code == 200
    with app.app_context():
        request = Request.query.filter_by(invoice=invoice).one()
    assert request.status == 20
    assert request.recipient_id == rgb_lib.Invoice(
        invoice).invoice_data().recipient_id
    wait_sched_process_pending(app)
    time.sleep(5)  # give the scheduler time to complete the send
    user['wallet'].refresh(user['online'], None, [])
    generate(1)
    user['wallet'].refresh(user['online'], None, [])
    assets = user['wallet'].list_assets([])
    assert any([assets.nia, assets.cfa])
    unspents = user['wallet'].list_unspents(user['online'], False)
    assert len(unspents) == 2  # 1 funding + 1 received (witness)


def test_receive_asset_witness_disallowed(get_app):
    """Test /receive/asset endpoint witness transfer is refused."""
    app = get_app(_app_prep_mainnet)
    client = app.test_client()

    user = prepare_user_wallets(app, 1)[0]

    # request using a witness tx invoice
    invoice = witness(app.config, user)
    resp = receive_asset(client, user["xpub"], invoice)
    assert resp.status_code == 403
    assert 'not supported on mainnet' in resp.json['error']


def test_receive_asset_witness_allowed(get_app):
    """Test /receive/asset endpoint witness transfer is allowed."""
    app = get_app(_app_prep_mainnet_witness_allowed)
    client = app.test_client()

    user = prepare_user_wallets(app, 1)[0]

    # request using a witness tx invoice
    invoice = witness(app.config, user)
    resp = receive_asset(client, user["xpub"], invoice)
    assert resp.status_code == 200


def test_receive_asset_random(get_app):
    """Test /receive/asset endpoint for random distribution."""
    app = get_app(_app_prep_random)
    client = app.test_client()

    user = prepare_user_wallets(app, 1)[0]

    # standard request
    scheduler.pause()
    resp = receive_asset(client, user["xpub"],
                         create_and_blind(app.config, user))
    assert resp.status_code == 200
    assert 'asset' in resp.json
    dist_conf = app.config['ASSETS']['group_1']['distribution']
    dist_resp = resp.json['distribution']
    assert dist_resp['mode'] == DistributionMode.RANDOM.value
    req_win_cfg = req_win_datetimes(dist_conf, app.config['DATE_FORMAT'])
    req_win_resp = req_win_datetimes(dist_resp, app.config['DATE_FORMAT'])
    assert req_win_resp['open'] == req_win_cfg['open']
    assert req_win_resp['close'] == req_win_cfg['close']


def test_receive_config(get_app):
    """Test /receive/config/<wallet_id> endpoint."""
    api = '/receive/config'
    app = get_app()
    client = app.test_client()

    # auth failure
    res = client.get(f"{api}/wallet_id", headers=BAD_HEADERS)
    assert res.status_code == 401

    bitcoin_network = getattr(rgb_lib.BitcoinNetwork, "REGTEST")
    xpub = rgb_lib.generate_keys(bitcoin_network).xpub
    wallet_id = get_sha256_hex(xpub)

    resp = client.get(f"{api}/{wallet_id}", headers=USER_HEADERS)
    assert resp.status_code == 200
    group = resp.json['groups']['group_1']
    assert group['label'] == 'group_1 for the test'
    assert group['distribution']['mode'] == 1
    assert 'requests_left' in group


def test_receive_config_random(get_app):
    """Test /receive/config/<wallet_id> endpoint for random distribution."""
    api = '/receive/config'
    app = get_app(_app_prep_random)
    client = app.test_client()

    bitcoin_network = getattr(rgb_lib.BitcoinNetwork, "REGTEST")
    xpub = rgb_lib.generate_keys(bitcoin_network).xpub
    wallet_id = get_sha256_hex(xpub)

    resp = client.get(f"{api}/{wallet_id}", headers=USER_HEADERS)
    assert resp.status_code == 200
    group = resp.json['groups']['group_1']
    assert group['label'] == 'group_1 for the test'
    dist_conf = app.config['ASSETS']['group_1']['distribution']
    dist_resp = group['distribution']
    assert group['distribution']['mode'] == 2
    req_win_cfg = req_win_datetimes(dist_conf, app.config['DATE_FORMAT'])
    req_win_resp = req_win_datetimes(dist_resp, app.config['DATE_FORMAT'])
    assert req_win_resp['open'] == req_win_cfg['open']
    assert req_win_resp['close'] == req_win_cfg['close']
    assert 'requests_left' in group


def test_reserve_topupbtc(get_app):
    """Test /reserve/top_up_btc endpoint."""
    api = '/reserve/top_up_btc'
    app = get_app()
    client = app.test_client()

    # prevent UTXO creation
    scheduler.pause()

    # auth failure
    res = client.get(api, headers=BAD_HEADERS)
    assert res.status_code == 401

    wallet = app.config['WALLET']
    user = prepare_user_wallets(app, 1)[0]

    # get an address
    resp = client.get(
        api,
        headers=OPERATOR_HEADERS,
    )
    assert resp.status_code == 200
    address = resp.json['address']

    # send some BTC + check the updated balance
    amount = 1000
    balance_1 = wallet.get_btc_balance(app.config['ONLINE']).vanilla
    txid = user['wallet'].send_btc(user['online'], address, amount,
                                   app.config['FEE_RATE'])
    assert txid
    balance_2 = wallet.get_btc_balance(app.config['ONLINE']).vanilla
    assert balance_2.settled == balance_1.settled
    assert balance_2.future == balance_1.future + amount
    assert balance_2.spendable == balance_1.spendable + amount

    # check settled balance updates after the tx gets confirmed
    generate(1)
    balance_3 = wallet.get_btc_balance(app.config['ONLINE']).vanilla
    assert balance_3.settled == balance_1.settled + amount


def test_reserve_topuprgb(get_app):  # pylint: disable=too-many-locals
    """Test /reserve/top_up_rgb endpoint."""
    api = '/reserve/top_up_rgb'
    app = get_app()
    client = app.test_client()

    # auth failure
    res = client.get(api, headers=BAD_HEADERS)
    assert res.status_code == 401

    wallet = app.config['WALLET']
    user = prepare_user_wallets(app, 1)[0]

    # send some assets from the faucet to the user wallet
    resp = receive_asset(client, user["xpub"],
                         create_and_blind(app.config, user))
    assert resp.status_code == 200
    asset = resp.json["asset"]
    asset_id = asset['asset_id']
    starting_balance = wallet.get_asset_balance(asset_id).settled
    wait_sched_process_pending(app)
    wait_xfer_status(user['wallet'], user['online'], asset_id, 1,
                     'WAITING_CONFIRMATIONS')
    # check balance updates once the transfer is SETTLED
    generate(1)
    wait_xfer_status(user['wallet'], user['online'], asset_id, 1, 'SETTLED')
    wait_xfer_status(wallet, app.config['ONLINE'], asset_id, 3, 'SETTLED')
    balance_1 = wallet.get_asset_balance(asset_id)
    assert balance_1.settled == (starting_balance - SEND_AMOUNT)

    # send some assets from the user to the faucet wallet
    resp = client.get(
        api,
        headers=OPERATOR_HEADERS,
    )
    assert resp.status_code == 200
    assert 'expiration' in resp.json
    invoice = resp.json['invoice']
    invoice_data = rgb_lib.Invoice(invoice).invoice_data()
    amount = 1
    recipient_map = {
        asset_id: [
            rgb_lib.Recipient(invoice_data.recipient_id, None, amount,
                              invoice_data.transport_endpoints),
        ]
    }
    created = user['wallet'].create_utxos(user['online'], True, 1,
                                          app.config['UTXO_SIZE'],
                                          app.config['FEE_RATE'])
    assert created == 1
    txid = user['wallet'].send(user['online'], recipient_map, True,
                               app.config['FEE_RATE'],
                               app.config['MIN_CONFIRMATIONS'])
    assert txid
    # check balance updates once the transfer is WAITING_CONFIRMATIONS
    wait_xfer_status(wallet, app.config['ONLINE'], asset_id, 4,
                     'WAITING_CONFIRMATIONS')
    balance_2 = wallet.get_asset_balance(asset_id)
    assert balance_2.settled == balance_1.settled
    assert balance_2.future == balance_1.future + amount
    assert balance_2.spendable == balance_1.spendable
    # check balance updates once the transfer is SETTLED
    generate(1)
    wait_xfer_status(wallet, app.config['ONLINE'], asset_id, 4, 'SETTLED')
    wait_xfer_status(user['wallet'], user['online'], asset_id, 2, 'SETTLED')
    balance_3 = wallet.get_asset_balance(asset_id)
    assert balance_3.settled == balance_2.settled + amount
    assert balance_3.future == balance_2.future
    assert balance_3.spendable == balance_2.spendable + amount
