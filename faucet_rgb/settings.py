"""Default application settings."""

import logging
import os
import sys

from flask import Flask


class Config():  # pylint: disable=too-few-public-methods
    """Create and configure the app."""
    # API key to access "public" APIs
    API_KEY = 'defaultapikey'
    # API key to access managament APIs
    API_KEY_OPERATOR = 'defaultoperatorapikey'
    # dictionary of the faucet's asset groups
    ASSETS = {}
    # if true, adjust the WSGI environ to use X-Forwarded-* headers
    BEHIND_PROXY = False
    # list of consignment endpoints
    # see https://github.com/RGB-Tools/rgb-http-json-rpc for the spec
    # see https://github.com/grunch/rgb-proxy-server for the implementation
    CONSIGNMENT_ENDPOINTS = [
        'rgbhttpjsonrpc:http://proxy.iriswallet.com/json-rpc'
    ]
    # faucet SQLite3 database file name
    DATABASE_NAME = 'db.sqlite3'
    # faucet data directory (absolute or relative)
    # relative paths are inside the instance directory
    DATA_DIR = 'data'
    # URL of the electrum server
    ELECTRUM_URL = 'ssl://electrum.iriswallet.com:50013'
    # fee rate for transactions
    FEE_RATE = 1.5
    # faucet's main log file name
    LOG_FILENAME = 'main.log'
    # faucet's scheduler log file name
    LOG_FILENAME_SCHED = 'scheduler.log'
    # log level for the console
    LOG_LEVEL_CONSOLE = 'INFO'
    # log level for the main log file (scheduler has fixed INFO level)
    LOG_LEVEL_FILE = 'DEBUG'
    # when there are pending requests, max wait in minutes before sending
    MAX_WAIT_MINUTES = 10
    # minimum number of pending requests to send even before MAX_WAIT_MINUTES
    MIN_REQUESTS = 10
    # mnemonic phrase for the underlying Bitcoin wallet
    MNEMONIC = None
    # faucet name
    NAME = None
    # Bitcoin network
    NETWORK = 'testnet'
    # interval, in seconds, between scheduler runs
    SCHEDULER_INTERVAL = 60
    # Flask/WSGI secret key
    # see https://flask.palletsprojects.com/en/2.2.x/config/#SECRET_KEY
    SECRET_KEY = 'defaultsecretkey'
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
    # and ASSETS on the startup, so you should not configure this directly
    NON_MIGRATION_GROUPS = None
    # cache for the current state of asset migration
    # { group_name: { wallet_id: asset_id } }
    # this is an internal variable that is computed from ASSET_MIGRATION_MAP
    # and the actual migration state in the db on the startup, so you should not
    # configure this directly
    ASSET_MIGRATION_CACHE = {}


class SchedulerFilter(logging.Filter):  # pylint: disable=too-few-public-methods
    """Filter out apscheduler logs."""

    def filter(self, record):
        if record.name.startswith('apscheduler'):
            return False
        return True


LOG_TIMEFMT = '%Y-%m-%d %H:%M:%S %z'
LOG_TIMEFMT_SIMPLE = '%d %b %H:%M:%S'
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'verbose': {
            'format':
            '[%(asctime)s] %(levelname).3s [%(name)s:%(lineno)s] %(threadName)s : %(message)s',
            'datefmt': LOG_TIMEFMT,
        },
        'simple': {
            'format': '%(asctime)s %(levelname).3s: %(message)s',
            'datefmt': LOG_TIMEFMT_SIMPLE,
        },
    },
    'handlers': {
        'console': {
            'level': Config.LOG_LEVEL_CONSOLE,
            'class': 'logging.StreamHandler',
            'formatter': 'simple',
            'stream': 'ext://sys.stdout',
            'filters': ['no_sched'],
        },
        'file': {
            'level': Config.LOG_LEVEL_FILE,
            'class': 'logging.handlers.RotatingFileHandler',
            'filename': Config.LOG_FILENAME,
            'maxBytes': 1048576,
            'backupCount': 7,
            'formatter': 'verbose',
            'filters': ['no_sched'],
        },
        'file_sched': {
            'level': 'INFO',
            'class': 'logging.handlers.RotatingFileHandler',
            'filename': Config.LOG_FILENAME_SCHED,
            'maxBytes': 1048576,
            'backupCount': 7,
            'formatter': 'verbose',
        },
    },
    'filters': {
        'no_sched': {
            '()': SchedulerFilter,
        },
    },
    'loggers': {
        '': {
            'handlers': ['console', 'file'],
            'level': 'DEBUG',
        },
        'apscheduler': {
            'handlers': ['file_sched'],
            'level': 'DEBUG',
        },
    },
}


def check_assets(app):
    """Check asset configuration is valid."""
    errors = []
    if not app.config['ASSETS']:
        errors = 'Cannot proceed without any configured RGB asset'
    for key, val in app.config['ASSETS'].items():
        if not key:
            errors.append('empty group key')
        if not val:
            errors.append(f'empty configuration for group {key}')
        if not val.get('label'):
            errors.append(f'missing label for group {key}')
        if not val.get('assets'):
            errors.append(f'missing assets for group {key}')
        for asset in val['assets']:
            if not asset.get('asset_id'):
                errors.append(
                    f'missing asset_id for asset {asset} in group {key}')
            if not asset.get('amount'):
                errors.append(
                    f'missing amount for asset {asset} in group {key}')
    if errors:
        print('issues parsing ASSETS configuration:')
        for error in errors:
            print(f' - {error}')
        sys.exit(1)


def check_config(app, log_dir):
    """Check the app configuration is valid."""
    # check database config
    if not app.config['DATABASE_NAME']:
        print('Cannot proceed without a configured database name')
        sys.exit(1)
    db_realpath = os.path.realpath(
        os.path.sep.join([app.config['DATA_DIR'],
                          app.config['DATABASE_NAME']]))
    app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{db_realpath}'

    # check the faucet name is configured
    if not app.config['NAME']:
        print('Cannot proceed without a configured faucet name')
        sys.exit(1)

    # check asset configuration
    check_assets(app)

    # ensure the instance and data directories exist
    for directory in (app.instance_path, app.config['DATA_DIR'], log_dir):
        try:
            os.makedirs(directory)
        except FileExistsError:
            pass


def get_app(name):
    """Return a configured Flask app."""
    app = Flask(name, instance_relative_config=True)

    # load configurations: default, instance, environment-provided
    app.config.from_object(Config)
    app.config.from_pyfile('config.py', silent=True)
    app.config.from_envvar('FAUCET_SETTINGS', silent=True)

    return app
