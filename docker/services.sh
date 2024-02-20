#!/usr/bin/env bash
set -e

prog=$(realpath "$(dirname "$0")")
name=$(basename "$0")


_cleanup() {
    # cd back to calling directory
    cd - >/dev/null || exit 1
}

_die () {
    echo "ERR: $*"
    exit 1
}


COMPOSE="docker compose"
if ! $COMPOSE >/dev/null; then
    _die "could not call docker compose (hint: install docker compose plugin)"
fi
COMPOSE="$COMPOSE -f docker-compose.yml"
BCLI="$COMPOSE exec -T -u blits bitcoind bitcoin-cli -regtest"
INITIAL_BLOCKS=111
DATA_DIR="./tmp"

help() {
    echo "$name help                show this help message"
    echo "$name fund <addr> <amt>   send 'amt' to 'addr' from bitcoind"
    echo "$name mine [num]          mine 'num' (default 1) blocks"
    echo "$name start               start the services"
    echo "$name stop                stop the services"
    exit 0
}

fund() {
    local address="$1"
    [ -n "$1" ] || _die "destination address required"
    $BCLI -rpcwallet=miner sendtoaddress "$address" 1
    mine
}

mine() {
    local blocks=1
    [ -n "$1" ] && blocks="$1"
    $BCLI -rpcwallet=miner -generate "$blocks"
}

start() {
    stop

    rm -rf $DATA_DIR
    mkdir -p $DATA_DIR
    # see docker-compose.yml for the exposed ports
    EXPOSED_PORTS=(3000 50001)
    for port in "${EXPOSED_PORTS[@]}"; do
        if [ -n "$(ss -HOlnt "sport = :$port")" ];then
            _die "port $port is already bound, services can't be started"
        fi
    done
    $COMPOSE up -d

    # wait for bitcoind to be up
    until $COMPOSE logs bitcoind |grep -q 'Bound to'; do
        sleep 1
    done
    # prepare bitcoind
    echo && echo "preparing bitcoind wallet"
    $BCLI createwallet miner >/dev/null
    mine $INITIAL_BLOCKS >/dev/null

    # wait for electrs to have completed startup
    until $COMPOSE logs electrs |grep -q 'finished full compaction'; do
        sleep 1
    done

    # wait for proxy to have completed startup
    until $COMPOSE logs proxy |grep -q 'App is running at http://localhost:3000'; do
        sleep 1
    done
}

stop() {
    $COMPOSE down -v --remove-orphans
}

# make sure to cleanup on exit
trap _cleanup EXIT INT TERM

# cd to script directory
cd "$prog" || exit

# cmdline arguments
[ -z "$1" ] && help
case $1 in
    help|start|stop) $1;;
    fund|mine) "$@";;
    *) _die "unsupported command \"$1\"";;
esac
