"""Wallet utils module."""

import string
import sys
from hashlib import sha256

import rgb_lib


def supported_schemas_from_config(supported_schemas):
    """Convert supported schemas from configuration strings to rgb-lib enum variants."""
    try:
        ss_enum_vars = [rgb_lib.AssetSchema[s] for s in supported_schemas]
    except KeyError as err:
        # TODO test this
        raise ValueError(f"Invalid supported schemas configuration: {err}") from err
    return ss_enum_vars


def wallet_data_from_config(cfg):
    """Return a wallet data dictionary with data from the app configuration."""
    supported_schemas = supported_schemas_from_config(cfg["SUPPORTED_SCHEMAS"])
    return {
        "xpub_colored": cfg["XPUB_COLORED"],
        "xpub_vanilla": cfg["XPUB_VANILLA"],
        "mnemonic": cfg["MNEMONIC"],
        "fingerprint": cfg["FINGERPRINT"],
        "data_dir": cfg["DATA_DIR"],
        "network": cfg["NETWORK"],
        "keychain": cfg["VANILLA_KEYCHAIN"],
        "supported_schemas": supported_schemas,
    }


def amount_from_assignment(assignment: rgb_lib.Assignment):
    """Return the amount corresponding to the given assignment."""
    if isinstance(assignment, rgb_lib.Assignment.FUNGIBLE):
        amount = assignment.amount
    elif isinstance(assignment, rgb_lib.Assignment.NON_FUNGIBLE):
        amount = 1
    elif isinstance(assignment, rgb_lib.Assignment.ANY):
        amount = 0
    else:
        raise ValueError(f"Unsupported assignment type: {assignment}")
    return amount


# TODO can these checks be move (relied upon) to settings.check_config ?
def init_wallet(electrum_url, wallet_data):
    """Initialize the wallet."""
    print("Initializing wallet...")
    if wallet_data["xpub_vanilla"] is None or wallet_data["xpub_colored"] is None:
        print("Wallet XPUBs not properly configured!")
        raise RuntimeError("Faucet unavailable")
    if wallet_data["mnemonic"] is None:
        print("Wallet mnemonic not configured!")
        raise RuntimeError("Faucet unavailable")
    if wallet_data["fingerprint"] is None:
        print("Wallet fingerprint not configured!")
        raise RuntimeError("Faucet unavailable")
    if not wallet_data["supported_schemas"]:
        print("Wallet supported schemas not configured!")
        raise RuntimeError("Faucet unavailable")
    # TODO check for supported networks
    network = wallet_data["network"]
    if not hasattr(rgb_lib.BitcoinNetwork, network.upper()):
        print(f'unsupported Bitcoin network "{network}"')
        sys.exit(1)
    bitcoin_network = getattr(rgb_lib.BitcoinNetwork, network.upper())
    try:
        wallet = rgb_lib.Wallet(
            rgb_lib.WalletData(
                data_dir=wallet_data["data_dir"],
                bitcoin_network=bitcoin_network,
                database_type=rgb_lib.DatabaseType.SQLITE,
                max_allocations_per_utxo=1,
                account_xpub_colored=wallet_data["xpub_colored"],
                account_xpub_vanilla=wallet_data["xpub_vanilla"],
                mnemonic=wallet_data["mnemonic"],
                master_fingerprint=wallet_data["fingerprint"],
                vanilla_keychain=wallet_data["keychain"],
                supported_schemas=wallet_data["supported_schemas"],
            )
        )
    except rgb_lib.RgbLibError as err:  # pylint: disable=catching-non-exception
        print("rgb_lib error:", err)
        raise RuntimeError("Faucet unavailable") from err
    online = wallet.go_online(False, electrum_url)
    wallet.refresh(online, None, [], False)
    return online, wallet


def get_unspent_list(wallet: rgb_lib.Wallet, online: rgb_lib.Online) -> list[rgb_lib.Unspent]:
    """Return a dict of the available unspents."""
    unspents = wallet.list_unspents(online, False, False)
    unspent_list = []
    for unspent in unspents:
        rgb_allocations_list = []
        for allocation in unspent.rgb_allocations:
            rgb_allocations_list.append(
                {
                    "asset_id": allocation.asset_id,
                    "amount": amount_from_assignment(allocation.assignment),
                    "settled": allocation.settled,
                }
            )
        unspent_dict = {
            "utxo": {
                "btc_amount": unspent.utxo.btc_amount,
                "colorable": unspent.utxo.colorable,
                "outpoint": {
                    "txid": unspent.utxo.outpoint.txid,
                    "vout": unspent.utxo.outpoint.vout,
                },
            },
            "rgb_allocations": rgb_allocations_list,
        }
        unspent_list.append(unspent_dict)
    return unspent_list


def is_walletid_valid(wallet_id):
    """Return if the given wallet ID is valid or not."""
    is_valid = False
    # check it's a SHA256-looking string
    allowed_chars = set(string.digits + string.ascii_lowercase[:6])
    if wallet_id and len(wallet_id) == 64 and set(wallet_id.lower()) <= allowed_chars:
        is_valid = True
    return is_valid


def get_sha256_hex(input_string):
    """Return the hex digest of the SHA256 for the given string."""
    return sha256(input_string.encode("utf-8")).hexdigest()
