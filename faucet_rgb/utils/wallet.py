"""Wallet utils module."""

import sys

import bdkpython as bdk
import rgb_lib
from flask import current_app

from faucet_rgb.utils import get_logger


def init_wallet(electrum_url, xpub, mnemonic, data_dir, network):
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
    online = wallet.go_online(False, electrum_url)
    wallet.refresh(online, None, [])
    return online, wallet


def _get_bdk_network():
    network = current_app.config['NETWORK'].upper()
    bdk_network = None
    if network == 'MAINNET':
        bdk_network = 'BITCOIN'
    if hasattr(bdk.Network, network):
        bdk_network = getattr(bdk.Network, network)
    if not bdk_network:
        raise RuntimeError("Could not get BDK network")
    return bdk_network


def get_unspent_dict(wallet, online):
    """Return a dict of the available unspents."""
    wallet.refresh(online, None, [])
    unspent_list = wallet.list_unspents(False)
    unspent_dict = {}
    for unspent in unspent_list:
        unspent_dict[str(
            unspent.utxo)] = [str(a) for a in unspent.rgb_allocations]
    return unspent_dict


def is_xpub_valid(xpub):
    """Return if the given XPub is valid or not."""
    logger = get_logger(__name__)
    is_valid = False
    try:
        network = _get_bdk_network()
        descriptor = bdk.Descriptor(f'wpkh({xpub})', network)
        bdk.Wallet(descriptor=descriptor,
                   change_descriptor=None,
                   network=network,
                   database_config=bdk.DatabaseConfig.MEMORY())
        is_valid = True
    except Exception as err:  # pylint: disable=broad-except
        logger.error('error checking xpub: %s', err)
    return is_valid
