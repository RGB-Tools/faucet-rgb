"""Wallet utils module."""

import sys

import bdkpython as bdk
import rgb_lib
from flask import current_app


def init_wallet(electrum_url, proxy_url, xpub, mnemonic, data_dir, network):
    """Initialize the wallet."""
    print('Initializing wallet...')
    if xpub is None:
        print('Wallet XPUB not configured!')
        raise RuntimeError('Faucet unavailable')
    if mnemonic is None:
        print('Wallet mnemonic not configured!')
        raise RuntimeError('Faucet unavailable')
    if not hasattr(rgb_lib.BitcoinNetwork, network.upper()):
        print(f'unsupported Bitcoin network "{network}"')
        sys.exit(1)
    bitcoin_network = getattr(rgb_lib.BitcoinNetwork, network.upper())
    try:
        wallet = rgb_lib.Wallet(
            rgb_lib.WalletData(
                data_dir,
                bitcoin_network,
                rgb_lib.DatabaseType.SQLITE,
                xpub,
                mnemonic,
            ), )
    except rgb_lib.RgbLibError as err:
        print('rgb_lib error:', err)
        raise RuntimeError('Faucet unavailable') from err
    online = wallet.go_online(False, electrum_url, proxy_url)
    wallet.refresh(online, None)
    return online, wallet


def is_xpub_valid(xpub):
    """Return if the given XPub is valid or not."""
    is_valid = False
    try:
        descriptor = f'wpkh({xpub})'
        bdk.Wallet(descriptor=descriptor,
                   change_descriptor=None,
                   network=bdk.Network.TESTNET,
                   database_config=bdk.DatabaseConfig.MEMORY())
        is_valid = True
    except Exception as err:
        current_app.logger.error('error checking xpub:', err)
    return is_valid
