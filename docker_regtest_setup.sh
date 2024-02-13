#!/usr/bin/env bash

CONFIG_FILE="config.py"
DATA_DIR="faucet_data"
SERVICE_DIR="service_data"

COMPOSE="docker compose"

BCLI="$COMPOSE exec -T -u blits bitcoind bitcoin-cli -regtest"
COMPOSE_EXEC="docker compose exec -T faucet bash -lc"

_tit() {
    echo
    echo "========================================"
    echo "$@"
    echo "========================================"
}

# build the faucet image
_tit "building docker image"
$COMPOSE build

# avoid overwriting an existing config file
_tit "performing initial checks"
if [ -r "$CONFIG_FILE" ] || [ -r "$DATA_DIR" ] || [ -r "$SERVICE_DIR" ]; then
    read -rp "existing data found, remove and continue? [y/N] " ans
    case $ans in
        y|Y)
            rm -r $CONFIG_FILE $DATA_DIR
            docker run --rm -v "$(pwd)":/data debian:bookworm \
                bash -c "rm -r /data/$SERVICE_DIR"
            ;;
        n|N)
            echo "aborting"
            exit 2
            ;;
        *)
            echo "unrecognized answer"
            exit 1
            ;;
    esac
else
    echo "all good"
fi

# initialize config file and data dirs
_tit "initializing the configuration file"
cat > $CONFIG_FILE <<EOF
NAME = "regtest faucet"
DATA_DIR = "/home/faucet/data"
NETWORK = "regtest"
ELECTRUM_URL = "tcp://electrs:50001"
CONSIGNMENT_ENDPOINTS = ['rpc:proxy:3000/json-rpc']
EOF
mkdir $DATA_DIR
chown 1000:1000 $DATA_DIR

_tit "initializing the wallet"
res="$($COMPOSE run --no-deps --rm -T faucet bash -lc "poetry run wallet-helper --init")"
mnemonic=$(echo "$res" |awk -F':' '/mnemonic/ {print $2}' | xargs)
xpub=$(echo "$res" |awk '/xpub/ {print $NF}')
cat >> $CONFIG_FILE <<EOF

MNEMONIC = "$mnemonic"
XPUB = "$xpub"
EOF

_tit "starting services"
docker compose down -v
$COMPOSE up -d electrs
# wait for bitcoind to be up
until $COMPOSE logs bitcoind |grep 'Bound to'; do
    sleep 1
done
# prepare bitcoin funds
$BCLI createwallet miner
$BCLI -rpcwallet=miner -generate 111
# wait for electrs to have completed startup
until $COMPOSE logs electrs |grep 'finished full compaction'; do
    sleep 1
done
# run a sleeping faucet container
faucet_container="$($COMPOSE run --no-deps -d faucet sleep 999)"

_tit "funding the wallet"
res="$($COMPOSE_EXEC "poetry run wallet-helper --address")"
address=$(echo "$res" |awk '/address:/ {print $NF}')
$BCLI -rpcwallet=miner sendtoaddress "$address" 1
$BCLI -rpcwallet=miner -generate 1

_tit "issuing and configuring an RGB asset"
res="$($COMPOSE_EXEC "poetry run issue-asset NIA 'fungible token' 0 1000 --ticker 'FFA' --unattended")"
asset_id=$(echo "$res" |awk '/asset ID:/ {print $NF}')
cat >> $CONFIG_FILE <<EOF

ASSETS = {
    'group': {
        'label': 'asset group',
        'distribution': {
            'mode': 1,
        },
        'assets': [
            {
                'asset_id': '$asset_id',
                'amount': 3,
            },
        ]
    },
}
EOF

_tit "stopping the services"
docker rm -f -v "$faucet_container"
docker compose down -v

_tit "setup complete"
echo "the regtest faucet is now ready"
echo "(start services with 'docker compose up -d')"
