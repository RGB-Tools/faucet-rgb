NAME = "example faucet"
DATA_DIR = "/home/faucet/data"
NETWORK = "regtest"
ELECTRUM_URL = "tcp://electrs:50001"
CONSIGNMENT_ENDPOINTS = ['rpc:proxy:3000/json-rpc']

MNEMONIC = "umbrella notice lens squirrel east food decrease remain wet vacuum juice slight"
XPUB = "tpubD6NzVbkrYhZ4Wp9BoVqe1Zcc3jsk4Ho8hP2Ge6WsSRFogQDqLsfdSg4W8NeAB2N1vUHq9SGNJKgBkGSVdhMDBDbsmAevdmzPn4TCRUdBMZ3"

ASSETS = {
    'group_name': {
        'label': 'asset group label',
        'distribution': {
            'mode': 1,
        },
        'assets': [
            {
                'asset_id': 'rgb:PWC5LNo-GmNK2MnDs-ErwTc7TSo-FsMNNAU1X-an486RNCL-PoHztm',
                'amount': 42,
            },
        ]
    },
}
