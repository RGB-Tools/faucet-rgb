"""Utils module."""

import rgb_lib


def init_wallet(electrum_url, xpub, mnemonic, data_dir):
    """Initialize the wallet."""
    print('Initializing wallet...')
    if xpub is None:
        print('Wallet XPUB not configured!')
        raise RuntimeError('Faucet unavailable')
    if mnemonic is None:
        print('Wallet mnemonic not configured!')
        raise RuntimeError('Faucet unavailable')
    try:
        wallet = rgb_lib.Wallet(
            rgb_lib.WalletData(
                data_dir,
                rgb_lib.BitcoinNetwork.TESTNET,
                rgb_lib.DatabaseType.SQLITE,
                xpub,
                mnemonic,
            ),
        )
    except rgb_lib.RgbLibError as err:
        print('rgb_lib error:', err)
        raise RuntimeError('Faucet unavailable') from err
    online = wallet.go_online(electrum_url, False)
    wallet.refresh(online, None)
    return online, wallet
