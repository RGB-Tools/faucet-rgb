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
from .settings import LOGGING, Config, check_config, get_app
from .utils.wallet import init_wallet


def print_assets_and_quit(assets, asset_id):
    """Print provided assets and asset ID, then terminate the process."""
    print('List of available rgb20 assets:')
    for asset in assets.rgb20:
        print(' -', asset.asset_id, asset.ticker, asset.name, asset.precision,
              asset.balance)
    print('List of available rgb121 assets:')
    for asset in assets.rgb121:
        print(' -', asset.asset_id, asset.name, asset.description,
              asset.precision, asset.parent_id, asset.data_paths,
              asset.balance)
    print(f'Cannot proceed: configured asset with id "{asset_id}" not found')
    sys.exit(1)


def create_app():
    """Create and configure the app."""
    app = get_app(__name__)

    # configure data files to go inside the data dir
    log_dir = os.path.sep.join([app.config['DATA_DIR'], 'logs'])
    for cfg_var in ('LOG_FILENAME', 'LOG_FILENAME_SCHED'):
        app.config[cfg_var] = os.path.sep.join([log_dir, app.config[cfg_var]])

    # configuration checks
    check_config(app, log_dir)

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
        app.config['ELECTRUM_URL'], app.config['XPUB'], app.config['MNEMONIC'],
        app.config['DATA_DIR'], app.config['NETWORK'])

    # ensure all the configured assets are available
    wallet = app.config['WALLET']
    assets = wallet.list_assets([])
    asset_ids = [asset.asset_id for asset in assets.rgb20 + assets.rgb121]
    for _, data in app.config['ASSETS'].items():
        for asset in data['assets']:
            asset_id = asset['asset_id']
            if asset_id not in asset_ids:
                print_assets_and_quit(assets, asset_id)

    # initialize DB
    db.init_app(app)
    with app.app_context():
        db.create_all()

    # register blueprints
    app.register_blueprint(control.bp)
    app.register_blueprint(receive.bp)
    app.register_blueprint(reserve.bp)

    # enable optional X-Forwarded-* headers usage
    if app.config['BEHIND_PROXY']:
        app.wsgi_app = ProxyFix(app.wsgi_app,
                                x_for=1,
                                x_proto=1,
                                x_host=1,
                                x_prefix=1)

    # intialize scheduler
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
