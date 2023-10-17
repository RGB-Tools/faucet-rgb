"""Wallet utils module."""

import string
import sys
from hashlib import sha256

import rgb_lib


def init_wallet(electrum_url, xpub, mnemonic, data_dir, network, keychain):
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
                1,
                xpub,
                mnemonic,
                keychain,
            ))
    except rgb_lib.RgbLibError as err:  # pylint: disable=catching-non-exception
        print('rgb_lib error:', err)
        raise RuntimeError('Faucet unavailable') from err
    online = wallet.go_online(False, electrum_url)
    wallet.refresh(online, None, [])
    return online, wallet


def get_unspent_list(wallet, online):
    """Return a dict of the available unspents."""
    unspents = wallet.list_unspents(online, False)
    unspent_list = []
    for unspent in unspents:
        rgb_allocations_list = []
        for allocation in unspent.rgb_allocations:
            rgb_allocations_list.append({
                'asset_id': allocation.asset_id,
                'amount': allocation.amount,
                'settled': allocation.settled,
            })
        unspent_dict = {
            'utxo': {
                'btc_amount': unspent.utxo.btc_amount,
                'colorable': unspent.utxo.colorable,
                'outpoint': {
                    'txid': unspent.utxo.outpoint.txid,
                    'vout': unspent.utxo.outpoint.vout,
                }
            },
            'rgb_allocations': rgb_allocations_list,
        }
        unspent_list.append(unspent_dict)
    return unspent_list


def is_walletid_valid(wallet_id):
    """Return if the given wallet ID is valid or not."""
    is_valid = False
    # check it's a SHA256-looking string
    allowed_chars = set(string.digits + string.ascii_lowercase[:6])
    if len(wallet_id) == 64 and set(wallet_id.lower()) <= allowed_chars:
        is_valid = True
    return is_valid


def get_sha256_hex(input_string):
    """Return the hex digest of the SHA256 for the given string."""
    return sha256(input_string.encode('utf-8')).hexdigest()
