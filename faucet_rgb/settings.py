"""Default application settings."""

import logging
import os
import sys
from datetime import datetime
from enum import Enum

from flask import Flask

from .exceptions import ConfigurationError

SUPPORTED_NETWORKS = ["mainnet", "testnet", "regtest"]


class DistributionMode(Enum):
    """Distribution modes.

    STANDARD: collect requests and send assets in batches
    RANDOM:   collect requests during a time interval and send assets to
              randomly-selected ones once the interval has ended; if there are
              more requests than assets, set the remaining requests as unmet
    """

    STANDARD = 1
    RANDOM = 2


class Config:  # pylint: disable=too-few-public-methods
    """Create and configure the app."""

    # API key to access "public" APIs
    API_KEY = "defaultapikey"
    # API key to access managament APIs
    API_KEY_OPERATOR = "defaultoperatorapikey"
    # dictionary of the faucet's asset groups
    ASSETS = {}
    # if true, adjust the WSGI environ to use X-Forwarded-* headers
    BEHIND_PROXY = False
    # list of transport endpoints, for invoices created by the faucet
    # see https://github.com/RGB-Tools/rgb-http-json-rpc for the spec
    # see https://github.com/RGB-Tools/rgb-proxy-server for the implementation
    TRANSPORT_ENDPOINTS = ["rpc://proxy.iriswallet.com/0.2/json-rpc"]
    # faucet SQLite3 database file name
    DATABASE_NAME = "db.sqlite3"
    # faucet data directory (absolute or relative)
    # relative paths are inside the instance directory
    DATA_DIR = "data"
    # URL of the electrum server
    ELECTRUM_URL = "ssl://electrum.iriswallet.com:50013"
    # fee rate for transactions
    FEE_RATE = 1.5
    # fingerprint of the underlying rgb-lib wallet
    FINGERPRINT = None
    # faucet's main log file name
    LOG_FILENAME = "main.log"
    # faucet's scheduler log file name
    LOG_FILENAME_SCHED = "scheduler.log"
    # log level for the console
    LOG_LEVEL_CONSOLE = "INFO"
    # log level for the main log file (scheduler has fixed INFO level)
    LOG_LEVEL_FILE = "DEBUG"
    # when there are pending requests, max wait in minutes before sending
    MAX_WAIT_MINUTES = 10
    # minimum number of pending requests to send even before MAX_WAIT_MINUTES
    MIN_REQUESTS = 10
    # mnemonic phrase for the underlying Bitcoin wallet
    MNEMONIC = None
    # faucet name
    NAME = None
    # Bitcoin network
    NETWORK = "testnet"
    # interval, in seconds, between scheduler runs
    SCHEDULER_INTERVAL = 60
    # Flask/WSGI secret key
    # see https://flask.palletsprojects.com/en/2.2.x/config/#SECRET_KEY
    SECRET_KEY = "defaultsecretkey"
    # if true, send a single asset per batch
    # see send_next_batch() in file faucet_rgb/scheduler.py
    SINGLE_ASSET_SEND = True
    # extended pubkey for the underlying Bitcoin wallet
    XPUB = None
    # dictionary mapping new asset IDs to old ones for migration
    # for each group, either none or all assets have to be mapped for migration
    ASSET_MIGRATION_MAP = None
    # set of asset groups which is not for migration from v0.9
    # this is an internal variable that is computed from ASSET_MIGRATION_MAP
    # and ASSETS on startup, so you should not configure this directly
    NON_MIGRATION_GROUPS = None
    # cache for the current state of asset migration
    # { group_name: { wallet_id: asset } }
    # this is an internal variable that is computed from ASSET_MIGRATION_MAP
    # and the actual migration state in the db on the startup, so you should not
    # configure this directly
    ASSET_MIGRATION_CACHE = {}
    # date format string
    DATE_FORMAT = "%Y-%m-%dT%H:%M:%S"
    # minimum number of confirmations before a transfer is considered settled
    MIN_CONFIRMATIONS = 1
    # amount in satoshi for sending witness txs
    AMOUNT_SAT = 1000
    # number of spare colorable UTXOS to keep
    SPARE_UTXO_NUM = 5
    # threshold for creating new colorable UTXOS
    SPARE_UTXO_THRESH = 2
    # size for new UTXOs to be created
    UTXO_SIZE = 1000
    # networks where witness tx is allowed
    WITNESS_ALLOWED_NETWORKS = ["testnet", "regtest"]
    # the change number to use for the vanilla (non-colored) keychain
    VANILLA_KEYCHAIN = 1


class SchedulerFilter(logging.Filter):  # pylint: disable=too-few-public-methods
    """Filter out apscheduler logs."""

    def filter(self, record):
        if record.name.startswith("apscheduler"):
            return False
        return True


LOG_TIMEFMT = "%Y-%m-%d %H:%M:%S %z"
LOG_TIMEFMT_SIMPLE = "%d %b %H:%M:%S"
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "verbose": {
            "format": (
                "[%(asctime)s] %(levelname).3s [%(name)s:%(lineno)s] "
                "%(threadName)s : %(message)s"
            ),
            "datefmt": LOG_TIMEFMT,
        },
        "simple": {
            "format": "%(asctime)s %(levelname).3s: %(message)s",
            "datefmt": LOG_TIMEFMT_SIMPLE,
        },
    },
    "handlers": {
        "console": {
            "level": Config.LOG_LEVEL_CONSOLE,
            "class": "logging.StreamHandler",
            "formatter": "simple",
            "stream": "ext://sys.stdout",
            "filters": ["no_sched"],
        },
        "file": {
            "level": Config.LOG_LEVEL_FILE,
            "class": "logging.handlers.RotatingFileHandler",
            "filename": Config.LOG_FILENAME,
            "maxBytes": 1048576,
            "backupCount": 7,
            "formatter": "verbose",
            "filters": ["no_sched"],
        },
        "file_sched": {
            "level": "INFO",
            "class": "logging.handlers.RotatingFileHandler",
            "filename": Config.LOG_FILENAME_SCHED,
            "maxBytes": 1048576,
            "backupCount": 7,
            "formatter": "verbose",
        },
    },
    "filters": {
        "no_sched": {
            "()": SchedulerFilter,
        },
    },
    "loggers": {
        "": {
            "handlers": ["console", "file"],
            "level": "DEBUG",
        },
        "apscheduler": {
            "handlers": ["file_sched"],
            "level": "DEBUG",
        },
    },
}


def check_distribution(app, group_name, group_val, errors):
    """Check distribution configuration for the given group."""
    err_begin = "missing distribution"
    err_end = f"for group {group_name}"
    dist_conf = group_val.get("distribution")
    if not dist_conf:
        errors.append(f"{err_begin} {err_end}")
        return
    dist_mode = dist_conf.get("mode")
    if not dist_mode:
        errors.append(f"{err_begin} mode {err_end}")
        return
    try:
        dist_mode = DistributionMode(dist_mode)
    except ValueError as err:
        errors.append(f'error "{err}" {err_end}')
        return
    if dist_mode == DistributionMode.RANDOM:
        _check_distribution_random(app.config, dist_conf, errors, err_begin, err_end)


def _check_distribution_random(cfg, dist_conf, errors, err_begin, err_end):
    dist_params = dist_conf.get("random_params")
    if not dist_params:
        errors.append(f"{err_begin} random params {err_end}")
        return
    params = ["request_window_open", "request_window_close"]
    for param in params:
        par = dist_params.get(param)
        if not par:
            errors.append(f"{err_begin} param {param} {err_end}")
            return
        try:
            datetime.strptime(par, cfg["DATE_FORMAT"])
        except ValueError as err:
            errors.append(f'error "{err}" for param {param} {err_end}')
    try:
        req_win_open = dist_params.get("request_window_open")
        req_win_close = dist_params.get("request_window_close")
        if req_win_open and req_win_close:
            req_win_open = datetime.strptime(req_win_open, cfg["DATE_FORMAT"])
            req_win_close = datetime.strptime(req_win_close, cfg["DATE_FORMAT"])
        if req_win_close <= req_win_open:
            errors.append(f"request window close {err_end} not after open")
    except ValueError:
        pass


def check_assets(app):
    """Check asset configuration is valid."""
    errors = []
    if not app.config["ASSETS"]:
        print(" *** WARNING! no configured RGB asset ***")
    for key, val in app.config["ASSETS"].items():
        if not val.get("label"):
            errors.append(f"missing label for group {key}")
        if not val.get("assets"):
            errors.append(f"missing assets for group {key}")
        check_distribution(app, key, val, errors)
        for asset in val["assets"]:
            if not asset.get("asset_id"):
                errors.append(f"missing asset_id for asset {asset} in group {key}")
            if not asset.get("amount"):
                errors.append(f"missing amount for asset {asset} in group {key}")
    if errors:
        print("issues parsing ASSETS configuration:")
        for error in errors:
            print(f" - {error}")
        raise ConfigurationError(errors)


def check_config(app, log_dir):
    """Check the app configuration is valid."""
    # check database config
    if not app.config["DATABASE_NAME"]:
        print("Cannot proceed without a configured database name")
        sys.exit(1)
    db_realpath = os.path.realpath(
        os.path.sep.join([app.config["DATA_DIR"], app.config["DATABASE_NAME"]])
    )
    app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{db_realpath}"

    # check the faucet name is configured
    if not app.config["NAME"]:
        print("Cannot proceed without a configured faucet name")
        sys.exit(1)

    # check network
    if app.config["NETWORK"] not in SUPPORTED_NETWORKS:
        print("Unsupported network. Supported ones:", ", ".join(SUPPORTED_NETWORKS))
        sys.exit(1)

    # check asset configuration
    check_assets(app)

    # ensure the instance and data directories exist
    for directory in (app.instance_path, app.config["DATA_DIR"], log_dir):
        try:
            os.makedirs(directory)
        except FileExistsError:
            pass


def get_app(name):
    """Return a configured Flask app."""
    app = Flask(name, instance_relative_config=True)

    # load configurations: default, instance, environment-provided
    app.config.from_object(Config)
    app.config.from_pyfile("config.py", silent=True)
    app.config.from_envvar("FAUCET_SETTINGS", silent=True)

    return app
