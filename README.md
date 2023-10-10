# RGB Faucet

## Requirements
- Python 3.9+
- Poetry 1.4+

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

### Asset migration

Wallets that received assets based on RGB v0.9 will lose them upon upgrading
to RGB v0.10. Asset migration is a feature that allows such wallets to request
an asset from the same asset group and receive the new version of the previous
asset, re-issued with v0.10.

By default, when a request for assets from a specific group is received, if
there is no previous request from the same wallet and group, a random asset from
the selected group is sent, otherwise no asset is sent and an error is returned.
This logic is still applied for asset groups that are not part of the migration
configuration.

Configuring `ASSET_MIGRATION_MAP`, asset groups that are included in the
configuration are no more part of the default logic. Instead, when a request
for assets from one such group is received, it will be checked against the
migration map. If the wallet ID matches a previous request for a v0.9 asset
being migrated, the new asset is sent, just once. Further requests by the same
wallet from the same group are denied.

Requesting from non-migration groups works as before, sending a random asset
from the selected group. Requesting with no group specified works as before,
sending a random asset from a random non-migration group.

For example, supposing the `ASSET` declaration above was done for RGB v0.9
assets, after upgrading to v0.10, re-issuing the assets and including a new
group `group_3` (which would operate with the default logic), it would become
something like:

```python
ASSETS = {
    'group_1': {
        'label': 'asset group one',
        'assets': [{
            'asset_id': 'Nixon...1oA',
            'amount': 1,
        }, {
            'asset_id': 'Visible...kEh',
            'amount': 7,
        }]
    },
    'group_2': {
        'label': 'asset group two',
        'assets': [{
            'asset_id': 'Express...uwg',
            'amount': 42,
        }, {
            'asset_id': 'Legacy...QBX',
            'amount': 4,
        }]
    },
    'group_3': {
        'label': 'asset group three',
        'assets': [{
            'asset_id': 'Nato...Vnx',
            'amount': 3,
        }, {
            'asset_id': 'Nadia...mXL',
            'amount': 11,
        }]
    },
}
```

and the following migration map would allow migrating the old assets in
`group_1` and `group_2`:

```python
ASSET_MIGRATION_MAP = {
    'Nixon...1oA': 'rgb1aaa...',
    'Visible...kEh': 'rgb1bbb...',
    'Express...uwg': 'rgb1ccc...',
    'Legacy...QBX': 'rgb1ddd...',
}
```

With this configuration, an example request for an asset from `group_1` from a
wallet that was previously sent asset `rgb1aaa` would trigger the sending of
asset `Nixon...1oA`

Note: when declaring `ASSET_MIGRATION_MAP`, all assets in a group need to be
defined, partial migration for a group is not supported.

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
  `<blinded_utxo>`; if no `asset_group` is provided, a random asset from a
  non-migration group is chosen
- `/receive/config/<wallet_id>` requests the faucet's configuration (name +
  groups), and the number of requests that are allowed for each group (only 1 or
  0 are possible at the moment)
  - `1` if the user can request sending from this group (including migration)
  - `0` if the user cannot request from this group anymore
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

### Database migration
Migrations are handles via `flask-migrate`.

To modify the DB structure:
- change the DB (database.py)
- setup a minimal faucet configuration in `instance/config.py`
    - NAME
    - XPUB (doesn't need to have funds)
    - MNEMONIC (doesn't need to have funds)
    - ASSETS (empty dict)
- run `poetry run flask --app faucet_rgb db migrate -m "<comment>"`
- check the generated migration file (Alembic is not always able to detect
  every change to models)
- commit the DB changes along with the generated migration file

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
poetry run issue-asset NIA "fungible token" 0 1000 1000 --ticker "FFA"
poetry run issue-asset CFA "CTB" 0 10 10 --description "a collectible" --file_path ./README.md
```

Finally, complete the configuration by defining the faucet's `NAME` and the
`ASSETS` dictionary with the issued assets.

## Testing/developing on regtest

### Setup

The `docker` directory contains a docker compose to run local copies of the
services required by the faucet to operate, configured for the regtest network.

The `services.sh` script is also included to start them:
```sh
./docker/services.sh start
```
The following services will be run in the background:
* bitcoind (regtest)
* electrs
* [rgb-proxy-server]

To configure the faucet to use these services, set the `ELECTRUM_URL` and
`TRANSPORT_ENDPOINTS` variables:
```py:config.py
ELECTRUM_URL="tcp://localhost:50001"
TRANSPORT_ENDPOINTS=["rpc:http://localhost:3000/json-rpc"]
```

Regtest wallets can also be funded using `services.sh` script:
```sh
./docker/services.sh fund <address> 1
```

Setup a faucet as in the [Initial setup example] section.

Using a different shell (as `FAUCET_SETTINGS` will need to be exported to a
different path), data directory and configuration file, setup a separate
instance as described in the [Initial setup example] section, up to the wallet
funding part (stop before issuing assets).
This separate instance will be used as an RGB-enabled wallet to request assets
from the faucet.

To tear down the services, run:
```sh
./docker/services.sh stop
```

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

### Integration test

Automated integration testing is supported via pytest.

To execute tests, run:
```sh
poetry run pytest
```

To execute a single test module run:
```sh
poetry run pytest <path/to/testfile.py>
```

To execute a single test run:
```sh
poetry run pytest <path/to/testfile.py>::<test_name>
```

Notes:
- output capture can be disabled by adding the `-s` pytest option
- output from passed tests can be shown at the end by adding the `-rP` pytest
  option

[rgb-proxy-server]: https://github.com/grunch/rgb-proxy-server
[Initial setup example]: #initial-setup-example
