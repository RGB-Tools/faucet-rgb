"""Development module to get wallet info with no running faucet."""

import argparse
import os
import sys

import rgb_lib
from rich import print as rp

from faucet_rgb import settings, utils


def _print_assets(asset_type, assets):
    rp(f'\n{asset_type} assets:')
    asset_dict = utils.get_asset_dict(assets)
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
    parser.add_argument('--blind',
                        action='store_true',
                        help='generate and print a new blinded UTXO')
    parser.add_argument('--unspents',
                        action='store_true',
                        help='print wallet unspents')
    args = parser.parse_args()

    app = settings.get_app(__name__)
    (data_dir, network) = (app.config['DATA_DIR'], app.config['NETWORK'])
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
                                              app.config['XPUB'],
                                              app.config['MNEMONIC'], data_dir,
                                              network)

    if args.address:
        print(f'new {network} wallet address: {wallet.get_address()}')

    if args.assets:
        assets = wallet.list_assets([])
        _print_assets('RGB20', assets.rgb20)
        _print_assets('RGB121', assets.rgb121)

    if args.blind:
        try:
            count = wallet.create_utxos(online, True, 1, None,
                                        app.config['FEE_RATE'])
            if count > 0:
                print(f'{count} new UTXOs created')
        except rgb_lib.RgbLibError.AllocationsAlreadyAvailable:
            pass
        except rgb_lib.RgbLibError.InsufficientBitcoins as err:
            print((f'Insufficient funds ({err.available} available sats).\n'
                   f'Funds can be sent to the following address'),
                  wallet.get_address())
            sys.exit(1)
        try:
            blind_data = wallet.blind(
                None,
                None,
                None,
                consignment_endpoints=[
                    'rgbhttpjsonrpc:http://localhost:3000/json-rpc'
                ])
            print(f'blinded_utxo: {blind_data.blinded_utxo}')
        except rgb_lib.RgbLibError as err:
            print(f'Error generating blind data: {err}')
            sys.exit(1)

    if args.unspents:
        rp('\nUnspents:')
        unspent_dict = utils.wallet.get_unspent_dict(wallet, online)
        rp(unspent_dict)
