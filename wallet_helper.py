"""Development module to get wallet info with no running faucet."""

import argparse
import os
import sys

import rgb_lib
from flask import Flask
from rich import print as rp

from faucet_rgb import settings, utils


def _print_assets(asset_type, assets):
    rp(f'\n{asset_type} assets:')
    asset_dict = {}
    for asset in assets:
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
            asset_dict[asset.asset_id]['data_paths'] = asset.data_paths
    rp(asset_dict)


def entrypoint():
    """Poetry script entrypoint."""
    parser = argparse.ArgumentParser(description='Wallet info.')
    parser.add_argument('--init',
                        action='store_true',
                        help='initialize a new wallet, print its data, exit')
    parser.add_argument('--address',
                        action='store_true',
                        help='print an address from the Bitcoin wallet')
    parser.add_argument('--assets',
                        action='store_true',
                        help='print current assets from RGB wallet')
    parser.add_argument('--unspents',
                        action='store_true',
                        help='print wallet unspents')
    args = parser.parse_args()

    # get flask app configuration
    app = Flask(__name__, instance_relative_config=True)
    app.config.from_object(settings.Config)
    app.config.from_pyfile('config.py', silent=True)
    app.config.from_envvar('FAUCET_SETTINGS', silent=True)

    data_dir = app.config['DATA_DIR']
    network = app.config['NETWORK']

    # setup
    if not os.path.exists(data_dir):
        os.makedirs(data_dir)

    # wallet initialization
    if args.init:
        if not hasattr(rgb_lib.BitcoinNetwork, network.upper()):
            print(f'unsupported Bitcoin network "{network}"')
            sys.exit(1)
        bitcoin_network = getattr(rgb_lib.BitcoinNetwork, network.upper())
        keys = rgb_lib.generate_keys(bitcoin_network)
        print(f'new {network} wallet keys:')
        print(' - mnemonic:', keys.mnemonic)
        print(' - xpub:', keys.xpub)
        sys.exit(0)  #

    # processing other argument
    online, wallet = utils.wallet.init_wallet(app.config['ELECTRUM_URL'],
                                              app.config['PROXY_URL'],
                                              app.config['XPUB'],
                                              app.config['MNEMONIC'], data_dir,
                                              network)

    if args.address:
        print(f'new {network} wallet address: {wallet.get_address()}')

    if args.assets:
        assets = wallet.list_assets([])
        _print_assets('RGB20', assets.rgb20)
        _print_assets('RGB21', assets.rgb21)

    if args.unspents:
        rp('\nUnspents:')
        wallet.refresh(online, None)
        unspent_list = wallet.list_unspents(False)
        unspent_dict = {}
        for unspent in unspent_list:
            unspent_dict[str(
                unspent.utxo)] = [str(a) for a in unspent.rgb_allocations]
        rp(unspent_dict)
