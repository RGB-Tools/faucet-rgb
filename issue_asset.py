"""Module to issue RGB20 and RGB121 assets."""

import argparse
import os
import sys

import rgb_lib

from faucet_rgb import settings, utils


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
    if args.schema.lower() == 'rgb20':
        if not args.ticker:
            print('missing ticker, which is required for RGB20 assets')
            sys.exit(1)
        _confirm_summary(args, common + ['ticker'])
        asset = wallet.issue_asset_rgb20(online, args.ticker, args.name,
                                         args.precision, args.amounts)
    elif args.schema.lower() == 'rgb121':
        _confirm_summary(args,
                         common + ['description', 'parent_id', 'file_path'])
        asset = wallet.issue_asset_rgb121(
            online, args.name, args.description, args.precision, args.amounts,
            args.parent_id if args.parent_id else None,
            args.file_path if args.file_path else None)
    else:
        print(f'unsupported schema "{args.schema}"')
        sys.exit(1)
    print(f'asset ID: {asset.asset_id}')


def entrypoint():
    """Poetry script entrypoint."""
    parser = argparse.ArgumentParser(description='Issue an asset.')
    # asset type
    parser.add_argument('schema', help='RGB20 or RGB121')
    # mandatory common arguments
    parser.add_argument('name', help='asset name')
    parser.add_argument('precision', type=int, help='asset precision')
    parser.add_argument('amounts', type=int, nargs='+', help='issuance amount')
    # optional schema-based arguments
    parser.add_argument('--ticker',
                        nargs='?',
                        help="Uppercase ticker for RGB20 assets")
    parser.add_argument('--description',
                        nargs='?',
                        help="Description for RGB121 assets")
    parser.add_argument('--parent_id',
                        nargs='?',
                        help='parent_id for RGB121 assets')
    parser.add_argument('--file_path',
                        nargs='?',
                        help='path to media file for RGB121 assets')
    args = parser.parse_args()

    app = settings.get_app(__name__)
    (data_dir, network) = (app.config['DATA_DIR'], app.config['NETWORK'])
    if not os.path.exists(data_dir):
        os.makedirs(data_dir)
    online, wallet = utils.wallet.init_wallet(app.config['ELECTRUM_URL'],
                                              app.config['XPUB'],
                                              app.config['MNEMONIC'], data_dir,
                                              network)

    # asset issuance
    try:
        count = wallet.create_utxos(online, True,
                                    len(args.amounts) + 2, None,
                                    app.config['FEE_RATE'])
        print(f'{count} new UTXOs created')
    except rgb_lib.RgbLibError.AllocationsAlreadyAvailable:
        pass
    except rgb_lib.RgbLibError.InsufficientBitcoins as err:
        print((f'Insufficient funds ({err.available} available sats).\n'
               f'Funds can be sent to the following address'), wallet.get_address())
        sys.exit(1)
    _issue_asset(wallet, online, args)
