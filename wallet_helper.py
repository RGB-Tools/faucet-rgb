"""Development module to get wallet info with no running faucet."""

import argparse
import os
import sys

import rgb_lib
from rich import print as rp

from faucet_rgb import settings, utils


def _print_assets(asset_type, assets):
    rp(f"\n{asset_type} assets:")
    asset_dict = utils.get_asset_dict(assets)
    rp(asset_dict)


def entrypoint():  # noqa: C901 # pylint: disable=too-many-statements
    """Poetry script entrypoint."""
    parser = argparse.ArgumentParser(description="Wallet info.")
    parser.add_argument(
        "--init", action="store_true", help="initialize a new wallet, print its data, exit"
    )
    parser.add_argument(
        "--address", action="store_true", help="print an address from the Bitcoin wallet"
    )
    parser.add_argument(
        "--assets", action="store_true", help="print current assets from RGB wallet"
    )
    parser.add_argument(
        "--blind", action="store_true", help="generate and print a new blinded UTXO"
    )
    parser.add_argument("--refresh", action="store_true", help="refresh all pending transfers")
    parser.add_argument("--unspents", action="store_true", help="print wallet unspents")
    args = parser.parse_args()

    app = settings.get_app(__name__)
    (data_dir, network) = (app.config["DATA_DIR"], app.config["NETWORK"])
    if not os.path.exists(data_dir):
        os.makedirs(data_dir)

    # wallet initialization
    if args.init:
        if not hasattr(rgb_lib.BitcoinNetwork, network.upper()):
            print(f'unsupported Bitcoin network "{network}"')
            sys.exit(1)
        bitcoin_network = getattr(rgb_lib.BitcoinNetwork, network.upper())
        keys = rgb_lib.generate_keys(bitcoin_network)
        print(f"new {network} wallet keys:")
        print(" - mnemonic:", keys.mnemonic)
        print(" - xpub:", keys.account_xpub)
        sys.exit(0)

    # processing other argument
    wallet_data = {
        "xpub": app.config["XPUB"],
        "mnemonic": app.config["MNEMONIC"],
        "data_dir": data_dir,
        "network": network,
        "keychain": app.config["VANILLA_KEYCHAIN"],
    }
    online, wallet = utils.wallet.init_wallet(app.config["ELECTRUM_URL"], wallet_data)

    if args.refresh:
        print("refreshing...")
        wallet.refresh(online, None, [])

    if args.address:
        print(f"new {network} wallet address: {wallet.get_address()}")

    if args.assets:
        assets = wallet.list_assets([])
        _print_assets("NIA", assets.nia)
        _print_assets("CFA", assets.cfa)

    if args.blind:
        # pylint: disable=duplicate-code
        try:
            count = wallet.create_utxos(
                online, True, 1, app.config["UTXO_SIZE"], app.config["FEE_RATE"]
            )
            if count > 0:
                print(f"{count} new UTXOs created")
        except rgb_lib.RgbLibError.AllocationsAlreadyAvailable:
            pass
        except rgb_lib.RgbLibError.InsufficientBitcoins as err:
            print(
                (
                    f"Insufficient funds ({err.available} available sats).\n"
                    f"Funds can be sent to the following address"
                ),
                wallet.get_address(),
            )
            sys.exit(1)
        # pylint: enable=duplicate-code
        try:
            blind_data = wallet.blind_receive(
                None, None, None, ["rpc://localhost:3000/json-rpc"], app.config["MIN_CONFIRMATIONS"]
            )
            print(f"blinded_utxo: {blind_data.recipient_id}")
        except rgb_lib.RgbLibError as err:  # pylint: disable=catching-non-exception
            print(f"Error generating blind data: {err}")
            sys.exit(1)

    if args.unspents:
        rp("\nUnspents:")
        unspent_dict = utils.wallet.get_unspent_list(wallet, online)
        rp(unspent_dict)
