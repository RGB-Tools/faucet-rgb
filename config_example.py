"""Example configuration file."""

NAME = "example faucet"
DATA_DIR = "/home/faucet/data"
NETWORK = "regtest"
ELECTRUM_URL = "tcp://electrs:50001"
CONSIGNMENT_ENDPOINTS = ["rpc:proxy:3000/json-rpc"]

MNEMONIC = "shrug announce follow quantum orchard coral reopen fiscal opinion invite burden broken"
FINGERPRINT = "61e63327"
XPUB_COLORED = "tpubDD26xb7XS2uJtMRXfKFYninfVQfkBgJQFKcdyxgbuV7Bvz7T67vKHesMF5jBCLnAG4qsix2vZkMpy659ArycZJ5wmFgcUwQitQvw9zLUcxt"
XPUB_VANILLA = "tpubDDLium7WLJDjxY6TPY4zk1jgjDpexiZTaMcZnv8jsvZ3HH1N6LDdoecHV4uQpz98DYkxSpwye2nUPURcxMf9zANWfdbcpzMpxj3T2LkCC6N"

ASSETS = {
    "group_name": {
        "label": "asset group label",
        "distribution": {
            "mode": 1,
        },
        "assets": [
            {
                "asset_id": "rgb:PWC5LNo-GmNK2MnDs-ErwTc7TSo-FsMNNAU1X-an486RNCL-PoHztm",
                "amount": 42,
            },
        ],
    },
}
