"""Faucet Flask app initialization and configuration."""

import logging
import os
import pathlib
import sys
import uuid
from logging.config import dictConfig

from flask import Flask, g, request
from werkzeug.middleware.proxy_fix import ProxyFix

from . import control, receive, reserve, tasks
from .database import Request, db
from .scheduler import scheduler
from .settings import LOGGING, Config
from .utils.wallet import init_wallet


def print_assets_and_quit(assets, asset_id):
    """Print provided assets and asset ID, then terminate the process."""
    print('List of available rgb20 assets:')
    for asset in assets.rgb20:
        print(' -', asset.asset_id, asset.ticker, asset.name, asset.precision,
              asset.balance)
    print('List of available rgb21 assets:')
    for asset in assets.rgb21:
        print(' -', asset.asset_id, asset.name, asset.description,
              asset.precision, asset.parent_id, asset.data_paths,
              asset.balance)
    print(f'Cannot proceed: configured asset with id "{asset_id}" not found')
    sys.exit(1)


def create_app():
    """Create and configure the app."""
    app = Flask(__name__, instance_relative_config=True)
    # load configurations: default, instance, environment-provided
    app.config.from_object(Config)
    app.config.from_pyfile('config.py', silent=True)
    app.config.from_envvar('FAUCET_SETTINGS', silent=True)

    # configure data files to go inside the data dir
    log_dir = os.path.sep.join([app.config['DATA_DIR'], 'logs'])
    for cfg_var in ('LOG_FILENAME', 'LOG_FILENAME_SCHED'):
        app.config[cfg_var] = os.path.sep.join([log_dir, app.config[cfg_var]])
    if not app.config['DATABASE_NAME']:
        print('Cannot proceed without a configured database name')
        sys.exit(1)
    db_realpath = os.path.realpath(
        os.path.sep.join([app.config['DATA_DIR'],
                          app.config['DATABASE_NAME']]))
    app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{db_realpath}'

    if not app.config['NAME']:
        print('Cannot proceed without a configured name')
        sys.exit(1)

    errors = []
    # if not app.config['ASSETS']:
    #     errors = 'Cannot proceed without any configured RGB asset'
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

    # ensure the instance and data directories exist
    for directory in (app.instance_path, app.config['DATA_DIR'], log_dir):
        try:
            os.makedirs(directory)
        except FileExistsError:
            pass

    # configure logging
    LOGGING['handlers']['file']['filename'] = app.config['LOG_FILENAME']
    LOGGING['handlers']['file_sched']['filename'] = app.config[
        'LOG_FILENAME_SCHED']
    LOGGING['handlers']['console']['level'] = app.config['LOG_LEVEL_CONSOLE']
    LOGGING['handlers']['file']['level'] = app.config['LOG_LEVEL_FILE']
    dictConfig(LOGGING)

    # pylint: disable=no-member
    @app.before_request
    def log_request():
        g.request_id = uuid.uuid4()
        app.logger.info(
            f'> {g.get("request_id")} {request.method} {request.full_path}')

    @app.after_request
    def log_response(response):
        app.logger.info(f'< {g.get("request_id")} {response.status}')
        return response

    # pylint: enable=no-member

    # initialize the wallet
    app.config['ONLINE'], app.config['WALLET'] = init_wallet(
        app.config['ELECTRUM_URL'], app.config['PROXY_URL'],
        app.config['XPUB'], app.config['MNEMONIC'], app.config['DATA_DIR'],
        app.config['NETWORK'])

    # ensure all the configured assets are available
    wallet = app.config['WALLET']
    assets = wallet.list_assets([])
    asset_ids = [asset.asset_id for asset in assets.rgb20 + assets.rgb21]
    for _, data in app.config['ASSETS'].items():
        for asset in data['assets']:
            asset_id = asset['asset_id']
            if asset_id not in asset_ids:
                print_assets_and_quit(assets, asset_id)

    db.init_app(app)

    with app.app_context():
        db.create_all()

    app.register_blueprint(control.bp)
    app.register_blueprint(receive.bp)
    app.register_blueprint(reserve.bp)

    if app.config['BEHIND_PROXY']:
        app.wsgi_app = ProxyFix(app.wsgi_app,
                                x_for=1,
                                x_proto=1,
                                x_host=1,
                                x_prefix=1)

    scheduler.init_app(app)
    scheduler.add_job(
        func=tasks.batch_donation,
        trigger='interval',
        seconds=app.config['SCHEDULER_INTERVAL'],
        id='batch_donation',
        replace_existing=True,
    )
    scheduler.start()

    return app
