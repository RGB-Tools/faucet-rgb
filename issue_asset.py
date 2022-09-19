"""Module to issue RGB assets."""

import argparse

import rgb_lib

from faucet_rgb import utils
from instance import config

def entrypoint():
    parser = argparse.ArgumentParser(description='Issue an RGB asset.')
    parser.add_argument('ticker')
    parser.add_argument('name')
    parser.add_argument('precision', type=int)
    parser.add_argument('amount', type=int)
    args = parser.parse_args()
    data_dir = getattr(config, 'DATA_DIR', './tmp')
    online, wallet = utils.init_wallet(
        'tcp://pandora.network:60001', config.XPUB, config.MNEMONIC, data_dir)
    try:
        asset = wallet.issue_asset(online, args.ticker, args.name, args.precision, args.amount)
        print(f'Asset ID: {asset.asset_id}')
    except rgb_lib.RgbLibError.InsufficientAllocationSlots:
        print('Not enough allocations, creating UTXOs...')
        wallet.create_utxos(online)
