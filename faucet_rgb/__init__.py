"""Faucet Flask app initialization and configuration."""

import os
import sys

from flask import Flask
from werkzeug.middleware.proxy_fix import ProxyFix

from . import receive, reserve, utils


def create_app():
    """Create and configure the app."""
    app = Flask(__name__, instance_relative_config=True)
    app.config.from_mapping(
        SECRET_KEY='dev',
        API_KEY='defaultapikey',
        BEHIND_PROXY=False,
        ELECTRUM_URL='tcp://pandora.network:60001',
        SENDING_AMT=15000,
        DATA_DIR='./tmp',
        XPUB=None,
        MNEMONIC=None,
        ASSETS={},
    )

    # load the instance config, if it exists
    app.config.from_pyfile('config.py', silent=True)

    if not app.config["ASSETS"]:
        print('Cannot proceed without any RGB asset configured')
        sys.exit(1)

    app.config["ONLINE"], app.config["WALLET"] = utils.init_wallet(
        app.config["ELECTRUM_URL"], app.config["XPUB"], app.config["MNEMONIC"],
        app.config["DATA_DIR"])

    # ensure the instance folder exists
    try:
        os.makedirs(app.instance_path)
    except OSError:
        pass

    app.register_blueprint(receive.bp)
    app.register_blueprint(reserve.bp)

    if app.config["BEHIND_PROXY"]:
        app.wsgi_app = ProxyFix(app.wsgi_app,
                                x_for=1,
                                x_proto=1,
                                x_host=1,
                                x_prefix=1)

    return app
