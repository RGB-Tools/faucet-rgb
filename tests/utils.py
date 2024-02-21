"""Utilities for tests"""

import json
import os
import shutil
import socket
import subprocess
import time
import urllib
from datetime import datetime

import rgb_lib
from flask import Flask
from flask_apscheduler import STATE_RUNNING

from faucet_rgb import create_app, scheduler, utils
from faucet_rgb.database import Request, db
from faucet_rgb.settings import Config
from faucet_rgb.utils.wallet import get_sha256_hex, wallet_data_from_config

BITCOIN_ARG = [
    "docker",
    "compose",
    "-f",
    "docker/docker-compose.yml",
    "exec",
    "-T",
    "-u",
    "blits",
    "bitcoind",
    "bitcoin-cli",
    "-regtest",
]
TRANSPORT_ENDPOINTS = ["rpc://localhost:3000/json-rpc"]
ELECTRUM_URL = "tcp://localhost:50001"
NETWORK = "regtest"
USER_HEADERS = {"x-api-key": Config.API_KEY}
OPERATOR_HEADERS = {"x-api-key": Config.API_KEY_OPERATOR}
BAD_HEADERS = {"x-api-key": 'wrongkey'}
ISSUE_AMOUNT = 1000
SEND_AMOUNT = 100


def get_test_name():
    """Get the currently running test name."""
    val = os.environ.get("PYTEST_CURRENT_TEST")
    assert val is not None, "must be called from tests"
    return val.split(":")[-1].split(" ")[0]


def get_test_datadir():
    """Get data_dir for the current test."""
    test_data = os.path.join(os.path.abspath(os.curdir), "test_data")
    return os.path.join(test_data, get_test_name())


def fund_address(addr):
    """A sendtoaddress rpc for the bitcoin node."""
    subprocess.run(
        BITCOIN_ARG + ["sendtoaddress", addr, "1"],
        capture_output=True,
        timeout=3000,
        check=True,
    )


def generate(num):
    """A generate command for the bitcoin node."""
    subprocess.run(
        BITCOIN_ARG + ["-generate", f"{num}"],
        capture_output=True,
        timeout=3000,
        check=True,
    )
    # wait for electrs to have synced the new block
    _wait_electrs_sync()


def _wait_electrs_sync():
    deadline = time.time() + 10
    # get bitcoind block count
    getblockcount = subprocess.run(
        BITCOIN_ARG + ["getblockcount"],
        capture_output=True,
        timeout=3000,
        check=True,
    )
    height = int(getblockcount.stdout.decode().strip())
    # wait for electrs the have reached the same height
    electrum = urllib.parse.urlparse(ELECTRUM_URL)
    message = {
        'method': 'blockchain.block.header',
        'params': [height],
        'id': 1,
    }
    request = json.dumps(message).encode('utf-8') + b'\n'
    while True:
        time.sleep(0.1)
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(3.0)
            sock.connect((electrum.hostname, electrum.port))
            sock.sendall(request)
            res = sock.recv(1024)
        response = json.loads(res)
        if response.get('result'):
            print('new height:', height)
            break
        if time.time() > deadline:
            raise RuntimeError('electrs not syncing with bitcoind')


def _get_user_wallet(data_dir):
    bitcoin_network = getattr(rgb_lib.BitcoinNetwork, NETWORK.upper())
    keys = rgb_lib.generate_keys(bitcoin_network)
    wallet_data = {
        'xpub': keys.xpub,
        'mnemonic': keys.mnemonic,
        'data_dir': data_dir,
        'network': NETWORK,
        'keychain': Config.VANILLA_KEYCHAIN,
    }
    online, wallet = utils.wallet.init_wallet(ELECTRUM_URL, wallet_data)
    return {"wallet": wallet, "xpub": keys.xpub, "online": online}


def prepare_user_wallets(app: Flask, num=1, start_num=0):
    """Prepare user wallets with UTXO.

    Its data will be put under `test_data/<function_name>/user<n>`.
    """
    users = []
    for i in range(start_num, start_num + num):
        data_dir = os.path.join(app.config["DATA_DIR"], f"user{i}")
        if os.path.exists(data_dir):
            shutil.rmtree(data_dir)
        os.mkdir(data_dir)
        user = _get_user_wallet(data_dir)
        users.append(user)

    for user in users:
        addr = user["wallet"].get_address()
        fund_address(addr)

    generate(1)

    return users


def issue_single_asset_with_supply(app, supply):
    """Issue 1 CFA asset with faucet-rgb's wallet.

    Returns a list with its asset ID, for compatibility with _issue_asset.
    """
    wallet = app.config["WALLET"]
    online = app.config["ONLINE"]
    wallet.create_utxos(online, True, None, app.config['UTXO_SIZE'],
                        app.config["FEE_RATE"])
    cfa = wallet.issue_asset_cfa(
        online,
        name="test with single CFA asset",
        description="a CFA asset for testing",
        precision=0,
        amounts=[supply],
        file_path=None,
    )
    return [cfa.asset_id]


def check_requests_left(app, xpub, group_to_requests_left):
    """Check requests_left for each asset group.

    requests_left is the one returned from /receive/config endpoint.

    Args:
        app (Flask): Flask app
        xpub (str): xpub for the user.
        group_to_requests_left (dict): (asset group) => (expected requests_left)
    """
    client = app.test_client()
    wallet_id = get_sha256_hex(xpub)
    resp = client.get(f"/receive/config/{wallet_id}", headers=USER_HEADERS)
    assert resp.status_code == 200
    for group, expected in group_to_requests_left.items():
        actual = resp.json["groups"][group]["requests_left"]
        assert expected == actual


def create_and_blind(config, user):
    """Create up to 1 UTXO and return an invoice with a blinded UTXO."""
    wallet = user["wallet"]
    _ = wallet.create_utxos(user["online"], True, 1, config['UTXO_SIZE'],
                            config["FEE_RATE"])
    receive_data = wallet.blind_receive(None, None, None,
                                        config["TRANSPORT_ENDPOINTS"],
                                        config['MIN_CONFIRMATIONS'])
    return receive_data.invoice


def witness(config, user):
    """Create up to 1 UTXO and return an invoice for a witness tx."""
    receive_data = user["wallet"].witness_receive(
        None, None, None, config["TRANSPORT_ENDPOINTS"],
        config['MIN_CONFIRMATIONS'])
    return receive_data.invoice


def add_fake_request(  # pylint: disable=too-many-arguments
        app,
        user,
        asset_group,
        status,
        amount=None,
        asset_id=None,
        hash_wallet_id=False):
    """Add a request to DB to simulate a previous request."""
    if amount is None:
        amount = app.config['ASSETS'][asset_group]['assets'][0]['amount']
    if asset_id is None:
        asset_id = app.config['ASSETS'][asset_group]['assets'][0]['asset_id']
    wallet_id = user["xpub"]
    if hash_wallet_id:
        wallet_id = get_sha256_hex(wallet_id)
    invoice = create_and_blind(app.config, user)
    invoice_data = rgb_lib.Invoice(invoice).invoice_data()
    with app.app_context():
        db.session.add(
            Request(wallet_id, invoice_data.recipient_id, invoice, asset_group,
                    asset_id, amount))
        req = Request.query.filter(Request.wallet_id == wallet_id,
                                   Request.invoice == invoice,
                                   Request.asset_group == asset_group,
                                   Request.status == 10)
        assert req.count() == 1
        req_idx = req.first().idx
        Request.query.filter_by(idx=req_idx).update({
            "status": status,
        })
        db.session.commit()


def receive_asset(client, xpub, invoice):
    """Call the /receive/asset API with the provided data."""
    return client.post(
        "/receive/asset",
        json={
            'wallet_id': get_sha256_hex(xpub),
            'invoice': invoice,
        },
        headers=USER_HEADERS,
    )


def check_receive_asset(app,
                        user,
                        group_to_request,
                        expected_status_code=200,
                        expected_asset_id_list=None):
    """Check the /receive/asset endpoint."""
    payload = {
        'wallet_id': get_sha256_hex(user["xpub"]),
        'invoice': create_and_blind(app.config, user)
    }
    if group_to_request:
        payload['asset_group'] = group_to_request
    client = app.test_client()
    resp = client.post("/receive/asset", json=payload, headers=USER_HEADERS)
    assert resp.status_code == expected_status_code
    if resp.status_code == 200 and expected_asset_id_list is not None:
        assert resp.json["asset"]["asset_id"] in expected_asset_id_list


def _prepare_utxos(app):
    wallet_data = wallet_data_from_config(app.config)
    online, wallet = utils.wallet.init_wallet(app.config["ELECTRUM_URL"],
                                              wallet_data)
    wallet.refresh(online, None, [])
    addr = wallet.get_address()
    fund_address(addr)
    generate(1)
    app.config["WALLET"] = wallet
    app.config["ONLINE"] = online
    return app


# purpose of this global variable is to give a unique value to the asset metadata
# each tests in pytest are run independently and it does not share global variable
# so having global here is not a problem
_ASSET_COUNT = 0


def _issue_asset(app):
    """Issue 1 NIA + 1 CFA assets with faucet-rgb's wallet.

    Returns a list of issued asset IDs.
    """
    global _ASSET_COUNT  # pylint: disable=global-statement
    _ASSET_COUNT += 1
    wallet = app.config["WALLET"]
    online = app.config["ONLINE"]
    wallet.create_utxos(online, True, None, app.config['UTXO_SIZE'],
                        app.config["FEE_RATE"])
    nia = wallet.issue_asset_nia(
        online,
        ticker=f"TFT{_ASSET_COUNT}",
        name=f"test NIA asset ({_ASSET_COUNT})",
        precision=0,
        amounts=[ISSUE_AMOUNT, ISSUE_AMOUNT],
    )
    cfa = wallet.issue_asset_cfa(
        online,
        name=f"test CFA asset ({_ASSET_COUNT})",
        description="a CFA asset for testing",
        precision=0,
        amounts=[ISSUE_AMOUNT, ISSUE_AMOUNT],
        file_path=None,
    )
    return [nia.asset_id, cfa.asset_id]


def prepare_assets(app,
                   group_name="group_1",
                   dist_mode=None,
                   issue_func=None,
                   send_amount=SEND_AMOUNT):
    """Issue (NIA, CFA) asset pair and set the config for the app.

    Issue ISSUE_AMOUNT units for each asset.
    The amount to be sent to users is SEND_AMOUNT

    Args:
        app (Flask): Flask app to configure.
        group_name (str): Name for the asset group ("group_1" by default).
    """
    if issue_func is None:
        issue_func = _issue_asset
    assets = issue_func(app)
    asset_list = [{"asset_id": a, "amount": send_amount} for a in assets]
    if dist_mode is None:
        dist_mode = {"mode": 1}
    app.config["ASSETS"][group_name] = {
        "distribution": dist_mode,
        "label": f"{group_name} for the test",
        "assets": asset_list,
    }
    return app


def _get_test_base_app():
    name = get_test_name()
    app = Flask(name, instance_relative_config=True)

    # base configutation
    app.config.from_object(Config)
    app.config["NAME"] = name
    app.config["DATA_DIR"] = get_test_datadir()

    # network settings
    app.config["ELECTRUM_URL"] = ELECTRUM_URL
    app.config["NETWORK"] = NETWORK
    app.config["TRANSPORT_ENDPOINTS"] = TRANSPORT_ENDPOINTS

    # scheduler settings (fast processing)
    app.config["MIN_REQUESTS"] = 1
    app.config["SCHEDULER_INTERVAL"] = 5

    return app


def _prepare_test_app(custom_app_prep):
    app = _get_test_base_app()

    bitcoin_network = getattr(rgb_lib.BitcoinNetwork, NETWORK.upper())
    keys = rgb_lib.generate_keys(bitcoin_network)

    app.config["FINGERPRINT"] = keys.xpub_fingerprint
    app.config["MNEMONIC"] = keys.mnemonic
    app.config["XPUB"] = keys.xpub

    # prepare utxos and assets
    app = _prepare_utxos(app)
    app.config["ASSETS"] = {}
    app = custom_app_prep(app)

    return app


def _reconfigure_test_app(config):
    app = _get_test_base_app()

    # re-configure wallet and assets
    app.config["FINGERPRINT"] = config['FINGERPRINT']
    app.config["MNEMONIC"] = config['MNEMONIC']
    app.config["XPUB"] = config['XPUB']
    app.config["WALLET"] = config['WALLET']
    app.config["ASSETS"] = config['ASSETS']
    app.config["ASSET_MIGRATION_MAP"] = config['ASSET_MIGRATION_MAP']

    return app


def create_test_app(config=None, custom_app_prep=None):
    """Returns a configured Flask app for the test.

    Args:
        config: if provided, use it to reconfigure the app
        custom_app_prep (function): if provided, run it after the app
            initialization. It must issue assets and configure for the app.
            Takes an app as an argument and returns the updated app.
    """

    def _custom_get_app():
        if config:
            return _reconfigure_test_app(config)
        if custom_app_prep:
            return _prepare_test_app(custom_app_prep)
        raise RuntimeError('config or custom_app_prep expected')

    return create_app(_custom_get_app, False)


def random_dist_mode(config, req_win_open, req_win_close):
    """Return dist_mode dict for random distribution."""
    date_fmt = config['DATE_FORMAT']
    return {
        "mode": 2,
        "random_params": {
            "request_window_open": datetime.strftime(req_win_open, date_fmt),
            "request_window_close": datetime.strftime(req_win_close, date_fmt),
        },
    }


def req_win_datetimes(dist_conf, date_format):
    """Return the parsed datetime for request window open/close."""
    return {
        'open':
        datetime.strptime(dist_conf['random_params']['request_window_open'],
                          date_format),
        'close':
        datetime.strptime(dist_conf['random_params']['request_window_close'],
                          date_format),
    }


def wait_refresh(wallet, online, asset=None):
    """Wait for refresh to return true (a transfer has changed)."""
    print('waiting for refresh to return True...')
    deadline = time.time() + 30
    while not wallet.refresh(online, asset, []):
        if time.time() > deadline:
            raise RuntimeError('refresh not returning True')
        time.sleep(1)
    print('refreshed')


def wait_xfer_status(wallet, online, asset_id, xfer_id, expected_status):
    """Wait for transfer with provided id to be in the expected status."""
    print(f'waiting for transfer {xfer_id} to be {expected_status}...')
    status = getattr(rgb_lib.TransferStatus, expected_status.upper())
    deadline = time.time() + 30
    while True:
        try:
            wallet.refresh(online, None, [])
            xfers = wallet.list_transfers(asset_id)
        except rgb_lib.RgbLibError.AssetNotFound:
            print("asset not found")
            time.sleep(1)
            continue
        for xfer in xfers:
            if xfer.idx == xfer_id and xfer.status == status:
                print(f'transfer {xfer_id} is {expected_status}')
                return
        if time.time() > deadline:
            raise RuntimeError(f'transfer {xfer_id} not {expected_status}')
        time.sleep(1)


def refresh_and_check_settled(client, config, asset_id):
    """Check that the transfer is settled."""
    resp = client.get(f"/control/refresh/{asset_id}", headers=OPERATOR_HEADERS)
    assert resp.status_code == 200
    assert resp.json['result'] is True
    asset_transfers = config['WALLET'].list_transfers(asset_id)
    transfer = [
        t for t in asset_transfers if t.kind == rgb_lib.TransferKind.SEND
    ][0]
    assert transfer.status == rgb_lib.TransferStatus.SETTLED


def wait_sched_process_pending(app):
    """Wait for scheduler to process pending requests and generate blocks."""
    print('waiting for scheduler to process PENDING requests...')
    assert scheduler.state == STATE_RUNNING
    with app.app_context():
        deadline = time.time() + 30
        while True:
            time.sleep(2)
            pending_requests = Request.query.filter(Request.status == 20)
            if not pending_requests.count():
                break
            print('pending requests:', pending_requests.count())
            if time.time() > deadline:
                raise RuntimeError('pending requests not getting served')
            generate(1)
    print('processed PENDING requests')


def wait_sched_process_waiting(app):
    """Wait for scheduler to process waiting requests."""
    print('waiting for scheduler to process WAITING requests...')
    assert scheduler.state == STATE_RUNNING
    with app.app_context():
        deadline = time.time() + 30
        while True:
            time.sleep(2)
            waiting_requests = Request.query.filter(Request.status == 25)
            if not waiting_requests.count():
                break
            print('waiting requests:', waiting_requests.count())
            if time.time() > deadline:
                raise RuntimeError('waiting requests not getting processed')
    print('processed WAITING requests')


def wait_sched_create_utxos(app):
    """Wait for scheduler to create new UTXOs."""
    assert scheduler.state == STATE_RUNNING
    print('waiting for scheduler to create UTXOs...')
    unspents = app.config['WALLET'].list_unspents(app.config['ONLINE'], False)
    starting_unspents = len(unspents)
    with app.app_context():
        deadline = time.time() + 30
        while True:
            time.sleep(2)
            unspents = app.config['WALLET'].list_unspents(
                app.config['ONLINE'], False)
            if len(unspents) > starting_unspents:
                break
            if time.time() > deadline:
                raise RuntimeError('pending requests not getting served')
            # generate(1)
    print('new UTXOs created')
