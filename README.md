# RGB Faucet

## Requirements
- Python 3.9+
- Poetry 1.2+

## Configuration

A default configuration is hard-coded in the `settings` module.

Configuration variables can then be overridden via a configuration file in
either of two locations. The first option is a `config.py` file inside the app
`instance` directory. The second option is a location provided via the
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
- `label` (string): a label for the group
- `assets` (list): a list of dictionaries, with each entry having the following
  items:
  - `asset_id` (string): the ID of the asset
  - `amount` (int): the amount to be sent to each recipient

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

See the `Config` class in the `faucet_rgb/settings.py` file for details on
configuration variables.

## Authentication

Endpoints require authentication via an API key, to be sent in the `X-Api-Key`
header.

There are two configurable API keys for authenticated requests:
 - `API_KEY`: user requests (e.g. `/receive/<wallet_id>/<blinded_utxo>`)
 - `API_KEY_OPERATOR`: operator requests (e.g. `/receive/requests`)

APIs will return an `{"error":"unauthorized"}` if the provided API key is
wrong.

## Endpoints

The available endpoints are:
- `/control/assets` list assets
- `/control/delete` delete failed transfers
- `/control/fail` fail pending transfers
- `/control/refresh/<asset_id>` requests a refresh for transfers of the given
  asset
- `/control/transfers?status=<status>` list transfers, pending ones by default
  or in the status (rgb-lib's TransferStatus) provided as query parameter
- `/control/unspents` returns the list of wallet unspents and related RGB
  allocations
- `/reserve/top_up_btc` returns the first unused address of the faucet's
  bitcoin wallet
- `/reserve/top_up_rgb` returns a blinded UTXO for the faucet's RGB wallet
- `/receive/asset/<wallet_id>/<blinded_utxo>?asset_group=<asset_group>` sends
  the configured amount of a random asset in optional group `<asset_group>` to
  `<blinded_utxo>`; if no group is provided, a random one is chosen;
- `/receive/config/<wallet_id>` requests the faucet's configuration (name +
  groups)
- `/receive/requests?asset_id=<asset_id>&blinded_utxo=<blinded_utco>&wallet_id=<wallet_id>`
  returns a list of received asset requests; can be filtered for `<asset_id>`,
  `<blinded_utxo>` or `<wallet_id>` via query parameters

Notes:
- `<wallet_id>` needs to be a valid xpub

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


To test the development server (`<wallet_id>` needs to be a valid xpub):
```shell
curl -i -H 'x-api-key: defaultapikey' localhost:5000/receive/config/<wallet_id>
```

## Production

To install the dependencies excluding the dev group:
```shell
poetry install --sync --without dev
```

Example running the app in production mode:
```shell
export FAUCET_SETTINGS=</path/to/config.py>
poetry run waitress-serve --host=127.0.0.1 --call 'faucet_rgb:create_app'
```

To test the production server locally (`<wallet_id>` needs to be a valid xpub):
```shell
curl -i -H 'x-api-key: defaultapikey' localhost:5000/receive/config/<wallet_id>
```

## Initial setup example

Choose a directory to hold the faucet data (e.g. `/srv/faucet`), create the
`config.py` file inside it, then export the `FAUCET_SETTINGS` environment
variable set to its path (e.g. `export FAUCET_SETTINGS=/srv/faucet/config.py`).

Configure the `DATA_DIR` and `NETWORK` parameters, then create a new wallet:
```shell
poetry run wallet-helper --init
```

Configure the printed `mnemonic` and `xpub` using the related (uppercase)
variables, then generate an address and send some bitcoins (e.g. 10k sats), to
be used for creating UTXOs to hold RGB allocations:
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

Issue at least one asset. If no allocation slots are available, some will be
created automatically. As an example:

> Note: issuance in RGB may require the wallet to create new UTXOs,
> It means it must somehow deal with the blockchain.
> The default configuration is for testnet. Thus to run the following command
> for other networks requires you to specify `ELECTRUM_URL` in `config.py`.


```shell
poetry run issue-asset rgb20 "fungible token" 0 1000 1000 --ticker "FFA"
poetry run issue-asset rgb121 "CTB" 0 10 10 --description "a collectible" --file_path ./README.md
```

Finally, complete the configuration by defining the faucet's `NAME` and the
`ASSETS` dictionary with the issued assets.

## Testing/developing on regtest

### Setup

The `docker` directory contains a docker-compose to run local copies of the
services required by the faucet to operate, configured for the regtest network.

The `start_services.sh` script is also included to start them:
```sh
cd docker
./start_services.sh
cd ..
```
The following services will be run in the background:
* bitcoind (regtest)
* electrs
* [rgb-proxy-server]

To configure the faucet to use these services, set the `ELECTRUM_URL` and
`CONSIGNMENT_ENDPOINTS` variables:
```py:config.py
ELECTRUM_URL="tcp://localhost:50001"
CONSIGNMENT_ENDPOINTS=["rgbhttpjsonrpc:http://localhost:3000/json-rpc"]
```

Funding wallets in the regtest environment can be done using bitcoind directly:
```sh
cd docker
docker-compose exec -T -u blits bitcoind bitcoin-cli -regtest sendtoaddress <address> 1
docker-compose exec -T -u blits bitcoind bitcoin-cli -regtest -generate 1
cd ..
```

Setup a faucet as in the [Initial setup example] section.

Using a different shell (as `FAUCET_SETTINGS` will need to be exported to a
different path), data directory and configuration file, setup a separate
instance as described in the [Initial setup example] section, up to the wallet
funding part (stop before issuing assets).
This separate instance will be used as an RGB-enabled wallet to request assets
from the faucet.

### Example asset request
Generate a blinded UTXO with the request wallet:
```sh
poetry run wallet-helper --blind
```

Call the faucet's `receive/asset` API using the request wallet xpub and the
generated blinded UTXO:
```sh
curl -i -H 'x-api-key: defaultapikey' localhost:5000/receive/asset/<xpub>/<blinded_utxo>
```


[rgb-proxy-server]: https://github.com/grunch/rgb-proxy-server
[Initial setup example]: #initial-setup-example
