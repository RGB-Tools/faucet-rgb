# RGB Faucet

## Endpoints

- `/control/assets` list assets
- `/control/delete` delete failed transfers
- `/control/fail` fail pending transfers
- `/control/refresh/<asset_id>` requests a refresh for transfers of the given
  asset
- `/control/transfers?status` list transfers, pending ones by default or
  in the status provided as query parameter
- `/control/unspents` returns the list of wallet unspents and related RGB
  allocations
- `/reserve/top_up_btc` returns the first unused address of the faucet's
  bitcoin wallet
- `/reserve/top_up_rgb` returns a faucet blinded UTXO
- `/receive/config` requests the faucet's configuration (name + groups)
- `/receive/requests?asset_id&blinded_utxo&wallet_id` returns a list of served
  requests; can be filtered for `asset_id`, `blinded_utxo` or `wallet_id` via
  query parameters
- `/receive/<wallet_id>/<blinded_utxo>?asset_group` sends the configured amount of an asset in
  optional group `group` to `<blinded_utxo>`; if no group is provided, a random
  one is chosen

## Requirements
- Python 3.9+
- Poetry 1.2+

## Configuration

A default configuration is hard-coded in the `settings` module.

Configuration variables can then be overridden via a configuration file in
either of two locations. The first option is a `config.py` file inside the app
instance directory. The second option is a location provided via the
environment variable `FAUCET_SETTINGS`. The two options can be combined, the
instance configuration will override the default one and the file pointed to by
the environment variable will take precedence, overriding both.

For the service to work it is necessary to configure at least the following
variables:
- `MNEMONIC`: the mnemonic for the wallet
- `XPUB`: the extended public key of the wallet
- `NAME`: the name of the faucet
- `ASSETS`: the dictionary of asset groups to be used by the faucet

The `ASSETS` variable is a dictionary with group names (strings) as keys. Each
group is a dictionary with the following fields:
- `label` (string): a label for the group, appears on wallets
- `assets` (list): a list of dictionaries, with each entry having the following
  items:
  - `asset_id` (string): the ID of the asset
  - `amount` (int): the amount to send to each recipient

An example `ASSETS` declaration:
```python
ASSETS = {
    'group_1': {
        'label': 'asset group one',
        'assets': [{
            'asset_id': 'rgb1aaa...',
            'amount': 1,
        }, {
            'asset_id': 'rgb1bbb...',
            'amount': 7,
        }]
    },
    'group_2': {
        'label': 'asset group two',
        'assets': [{
            'asset_id': 'rgb1ccc...',
            'amount': 42,
        }, {
            'asset_id': 'rgb1ddd...',
            'amount': 4,
        }]
    },
}
```

## Authentication

Some endpoints are open and do not require authentication (e.g.
`/receive/config`) while others require authentication via an API key to be
sent in the `X-Api-Key` header.

There are two configurable API keys for authenticated requests:
 - `API_KEY`: user requests (e.g. `/receive/<wallet_id>/<blinded_utxo>`)
 - `API_KEY_OPERATOR`: operator requests (e.g. `/receive/requests`)

## Development

To install the dependencies excluding the production group:
```shell
poetry install --without production
```

To run the app in development mode:
```shell
poetry run flask --app faucet_rgb run --no-reload
```
Notes:
- `--no-reload` is required to avoid trying to restart RGB services, which
fails trying to acquire a lock on open database files.
- using `--debug` will prevent the scheduler from running


To test the development server:
```shell
curl -i localhost:5000/receive/config
```

To test an authenticated call to the development server:
```shell
curl -i -H 'x-api-key: defaultapikey' localhost:5000/receive/id/blindedutxo
```
will return an "unauthorized" error if the API key is wrong.

## Production

To install the dependencies excluding the dev group:
```shell
poetry install --sync --without dev
```

Example running the app in production mode:
```shell
export FAUCET_SETTINGS=/home/user/rgb-faucet/config.py
poetry run waitress-serve --host=127.0.0.1 --call 'faucet_rgb:create_app'
```

To test the production server locally:
```shell
curl -i localhost:8080/receive/config
```

## Initial setup

Configure the `DATA_DIR` and `NETWORK` parameters, then create a new wallet:
```shell
poetry run wallet-helper --init
```

Configure the printed `mnemonic` and `xpub`, then generate an address and send
some bitcoins, to be used for creating UTXOs to hold RGB allocations:
```shell
poetry run wallet-helper --address
```

Once mnemonic and XPub have been configured, the `wallet-helper` script can
also provide info on the wallet status, which might be useful during the
initial setup:
```shell
poetry run wallet-helper --unspents
poetry run wallet-helper --assets
```

Issue at least one asset. If no allocation slots are available, some are
created automatically. As an example:
```shell
poetry run issue-asset rgb20 "fungible token" 0 1000 1000 --ticker "FFA"
poetry run issue-asset rgb21 "NFT" 0 10 10 --description "a collectible" --file_path ./README.md
```

Finally, write the complete configuration, including the issued assets under
the `ASSETS` variable, to the instance configuration or to a separate file that
will be exported via the `FAUCET_SETTINGS` environment variable.
