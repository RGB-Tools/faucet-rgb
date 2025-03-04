"""Tests for a specific issuance case."""

import rgb_lib


def test_max_issuance_split(get_app):  # pylint: disable=too-many-locals
    """Test max issuance amount split into 8 UTXOs."""
    app = get_app()
    wallet = app.config["WALLET"]
    online = app.config["ONLINE"]
    wallet.create_utxos(online, True, 8, app.config["UTXO_SIZE"], app.config["FEE_RATE"], False)
    max_supply = 2**64 - 1
    amount = 2**61
    nia = wallet.issue_asset_nia(
        online,
        ticker="MAX",
        name="max issuance test",
        precision=2,
        amounts=[
            amount,
            amount,
            amount,
            amount,
            amount,
            amount,
            amount,
            amount - 1,
        ],
    )
    print(f"asset: {nia}")
    assert nia.issued_supply == max_supply

    unspents = wallet.list_unspents(online, False, False)
    count_1 = 0
    count_2 = 0
    print("unspents:")
    for e in unspents:
        print(f"  - {e.utxo.outpoint} {e.utxo.btc_amount} {e.utxo.colorable} {e.utxo.exists}")
        for a in e.rgb_allocations:
            print(f"    * {a}")
            if a.amount == amount:
                count_1 += 1
            elif a.amount == amount - 1:
                count_2 += 1
    assert count_1 == 7
    assert count_2 == 1

    assets = wallet.list_assets([])
    print("assets:")
    found = False
    for e in assets.nia:
        print(f"  - {e}")
        if e.ticker == "MAX":
            found = True
            assert e.issued_supply == max_supply
    assert found

    transfers = wallet.list_transfers(nia.asset_id)
    print("transfers:")
    for e in transfers:
        print(f"  - {e}")
    assert len(transfers) == 1
    assert transfers[0].kind == rgb_lib.TransferKind.ISSUANCE
    assert transfers[0].amount == max_supply
