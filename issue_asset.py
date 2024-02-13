"""Module to issue NIA and CFA assets."""

import argparse
import os
import sys

import rgb_lib

from faucet_rgb import settings, utils
from faucet_rgb.utils.wallet import wallet_data_from_config


def _confirm_summary(args, to_print):
    print(f"You're about to issue the following {args.schema} asset:")
    for arg in to_print:
        print(f' - {arg}: {getattr(args, arg)}')
    print('are you sure you want to issue this asset? [y/n] ', end='')
    user_input = input()
    if user_input.lower() != 'y':
        print('aborting')
        sys.exit(0)


def _issue_asset(wallet, online, args):
    common = ['name', 'precision', 'amounts']
    if args.schema.lower() == 'nia':
        if not args.ticker:
            print('missing ticker, which is required for NIA assets')
            sys.exit(1)
        if not args.unattended:
            _confirm_summary(args, common + ['ticker'])
        asset = wallet.issue_asset_nia(online, args.ticker, args.name,
                                       args.precision, args.amounts)
    elif args.schema.lower() == 'cfa':
        _confirm_summary(args, common + ['description', 'file_path'])
        asset = wallet.issue_asset_cfa(
            online, args.name, args.description, args.precision, args.amounts,
            args.file_path if args.file_path else None)
    else:
        print(f'unsupported schema "{args.schema}"')
        sys.exit(1)
    print(f'asset ID: {asset.asset_id}')


def entrypoint():
    """Poetry script entrypoint."""
    parser = argparse.ArgumentParser(description='Issue an asset.')
    # asset type
    parser.add_argument('schema', help='NIA or CFA')
    # mandatory common arguments
    parser.add_argument('name', help='asset name')
    parser.add_argument('precision', type=int, help='asset precision')
    parser.add_argument('amounts', type=int, nargs='+', help='issuance amount')
    # optional schema-based arguments
    parser.add_argument('--ticker',
                        nargs='?',
                        help="Uppercase ticker for NIA assets")
    parser.add_argument('--description',
                        nargs='?',
                        help="Description for CFA assets")
    parser.add_argument('--file_path',
                        nargs='?',
                        help='path to media file for CFA assets')
    # optional confirmation check skipping
    parser.add_argument('--unattended',
                        action='store_true',
                        help='issue without prompting for confirmation')
    args = parser.parse_args()

    app = settings.get_app(__name__)
    (data_dir, network) = (app.config['DATA_DIR'], app.config['NETWORK'])
    if not os.path.exists(data_dir):
        os.makedirs(data_dir)
    wallet_data = wallet_data_from_config(app.config)
    online, wallet = utils.wallet.init_wallet(app.config['ELECTRUM_URL'],
                                              wallet_data)

    # asset issuance
    try:
        count = wallet.create_utxos(online, True,
                                    len(args.amounts) + 2,
                                    app.config['UTXO_SIZE'],
                                    app.config['FEE_RATE'])
        print(f'{count} new UTXOs created')
    except rgb_lib.RgbLibError.AllocationsAlreadyAvailable:
        pass
    except rgb_lib.RgbLibError.InsufficientBitcoins as err:
        print((f'Insufficient funds ({err.available} available sats).\n'
               f'Funds can be sent to the following address'),
              wallet.get_address())
        sys.exit(1)
    _issue_asset(wallet, online, args)
