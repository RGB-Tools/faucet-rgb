"""Faucet Flask app initialization and configuration."""

import itertools
import os
import sys
import uuid
from logging.config import dictConfig

from flask import g, request
from flask_apscheduler import STATE_STOPPED
from flask_migrate import upgrade
from sqlalchemy import and_
from werkzeug.middleware.proxy_fix import ProxyFix

from . import control, receive, reserve, tasks
from .database import Request, db, migrate
from .scheduler import scheduler
from .settings import LOGGING, check_config, get_app
from .utils.wallet import get_sha256_hex, init_wallet, wallet_data_from_config


def print_assets_and_quit(assets, asset_id):
    """Print provided assets and asset ID, then terminate the process."""
    print("List of available NIA assets:")
    for asset in assets.nia:
        print(
            " -",
            asset.asset_id,
            asset.ticker,
            asset.name,
            asset.precision,
            asset.balance,
        )
    print("List of available CFA assets:")
    for asset in assets.cfa:
        print(
            " -",
            asset.asset_id,
            asset.name,
            asset.description,
            asset.precision,
            asset.data_paths,
            asset.balance,
        )
    print(f'Cannot proceed: configured asset with id "{asset_id}" not found')
    sys.exit(1)


def validate_migration_map(app):
    """Ensure the sanity of `ASSET_MIGRATION_MAP`

    New asset IDs in `ASSET_MIGRATION_MAP` (if any) must also be defined in the
    `ASSETS` section.
    """
    mig_map = app.config["ASSET_MIGRATION_MAP"]
    if mig_map is None:
        app.config["NON_MIGRATION_GROUPS"] = set(app.config["ASSETS"])
        return
    groups_to = set()
    for asset_id in mig_map:
        containing_group = None
        for group_name, group_data in app.config["ASSETS"].items():
            for asset in group_data["assets"]:
                if asset["asset_id"] == asset_id:
                    containing_group = group_name
        if containing_group is None:
            print(f"error in ASSET_MIGRATION_MAP! asset {asset_id} is not " "defined in any group!")
            sys.exit(1)

        groups_to.add(containing_group)

    # check all assets in migration groups are defined as migration destination
    dest_asset_ids = mig_map.keys()
    for group_to in groups_to:
        for asset in app.config["ASSETS"][group_to]["assets"]:
            asset_id = asset["asset_id"]
            if asset_id not in dest_asset_ids:
                print(
                    f"asset ID {asset_id} is not defined as a migration "
                    "destination while other assets in the same group are!"
                )
                sys.exit(1)
    app.config["NON_MIGRATION_GROUPS"] = set(app.config["ASSETS"]) - groups_to


def _get_group_and_asset_from_id(app, asset_id):
    for group_name, group_data in app.config["ASSETS"].items():
        for asset in group_data["assets"]:
            if asset["asset_id"] == asset_id:
                return (group_name, asset)
    raise KeyError(asset_id)


def _get_all_requests_waiting_for_migration(rev_mig_map):
    """Gather all requests which haven't completed migration."""
    reqs = (
        Request.query.filter(Request.status == 40)  # consider only "served" status
        .order_by(Request.wallet_id)
        .all()
    )
    reqs_waiting_for_migration = []
    for _, same_wallet_requests in itertools.groupby(reqs, lambda r: r.wallet_id):
        it1, it2 = itertools.tee(same_wallet_requests, 2)
        for req in it1:
            new_asset_id = rev_mig_map.get(req.asset_id)
            if new_asset_id is None:
                continue
            wallet_migration_complete = any(r.asset_id == new_asset_id for r in it2)
            if not wallet_migration_complete:
                reqs_waiting_for_migration.append(req)
    return reqs_waiting_for_migration


def create_user_migration_cache(app):
    """Create `ASSET_MIGRATION_CACHE`, which is used later to perform migration.

    See settings.py::Config for more details about the cache.
    """
    mig_map = app.config["ASSET_MIGRATION_MAP"]
    if mig_map is None:
        return

    with app.app_context():
        rev_mig_map = {v: k for k, v in mig_map.items()}

        reqs_waiting_for_migration = _get_all_requests_waiting_for_migration(rev_mig_map)

        # build asset migration cache
        mig_cache = {}
        for req in reqs_waiting_for_migration:
            new_asset_id = rev_mig_map.get(req.asset_id)
            if new_asset_id is not None:
                group, asset = _get_group_and_asset_from_id(app, new_asset_id)
                if group not in mig_cache:
                    mig_cache[group] = {}
                # only consider (old) requests with xPub wallet ID
                if len(req.wallet_id) > 64:
                    wallet_id = get_sha256_hex(req.wallet_id)
                    if wallet_id not in mig_cache[group]:
                        mig_cache[group][wallet_id] = asset
        app.config["ASSET_MIGRATION_CACHE"] = mig_cache

        # update pending requests for old assets
        for req in Request.query.filter(
            and_(Request.status != 40, Request.asset_id.in_(rev_mig_map.keys()))
        ):
            # if there is a pending request for an old asset,
            # update it with the new asset_id
            req.asset_id = rev_mig_map[req.asset_id]
            db.session.add(req)
        db.session.commit()

        # log the current migration state
        if len(mig_cache):
            remaining = len(set().union(*mig_cache.values()))
            app.logger.info(f"{remaining} wallets are still not fully migrated.")
        else:
            app.logger.warning(
                "All wallets are migrated! You can drop `ASSET_MIGRATION_MAP` from config now."
            )


def create_app(custom_get_app=None, do_init_wallet=True):
    """Create and configure the app.

    Args:
        custom_get_app: Function that returns a configured app.
            Used for custom configuration from the test code.
        do_init_wallet: Set to False to skip wallet initialization.
    """
    app = get_app(__name__) if custom_get_app is None else custom_get_app()

    # configure data files to go inside the data dir
    log_dir = os.path.sep.join([app.config["DATA_DIR"], "logs"])
    for cfg_var in ("LOG_FILENAME", "LOG_FILENAME_SCHED"):
        app.config[cfg_var] = os.path.sep.join([log_dir, app.config[cfg_var]])

    # configuration checks
    check_config(app, log_dir)

    validate_migration_map(app)

    # initialize the wallet
    if do_init_wallet:
        wallet_data = wallet_data_from_config(app.config)
        app.config["ONLINE"], app.config["WALLET"] = init_wallet(
            app.config["ELECTRUM_URL"], wallet_data
        )

    # ensure all the configured assets are available
    wallet = app.config["WALLET"]
    assets = wallet.list_assets([])
    asset_ids = [asset.asset_id for asset in assets.nia + assets.cfa]
    for _, data in app.config["ASSETS"].items():
        for asset in data["assets"]:
            asset_id = asset["asset_id"]
            if asset_id not in asset_ids:
                print_assets_and_quit(assets, asset_id)

    # initialize DB
    db.init_app(app)
    migrate.init_app(app, db)
    with app.app_context():
        upgrade()

    # configure logging (needs to be after migration as alembic resets it)
    LOGGING["handlers"]["file"]["filename"] = app.config["LOG_FILENAME"]
    LOGGING["handlers"]["file_sched"]["filename"] = app.config["LOG_FILENAME_SCHED"]
    LOGGING["handlers"]["console"]["level"] = app.config["LOG_LEVEL_CONSOLE"]
    LOGGING["handlers"]["file"]["level"] = app.config["LOG_LEVEL_FILE"]
    dictConfig(LOGGING)

    # pylint: disable=no-member
    @app.before_request
    def log_request():
        g.request_id = uuid.uuid4()
        app.logger.info("> %s %s %s", g.get("request_id"), request.method, request.full_path)

    @app.after_request
    def log_response(response):
        app.logger.info("< %s %s", g.get("request_id"), response.status)
        return response

    # pylint: enable=no-member

    create_user_migration_cache(app)

    # register blueprints
    app.register_blueprint(control.bp)
    app.register_blueprint(receive.bp)
    app.register_blueprint(reserve.bp)

    # enable optional X-Forwarded-* headers usage
    if app.config["BEHIND_PROXY"]:
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)

    # initialize the scheduler, only if not already running
    # this is necessary when re-starting the app from tests
    if scheduler.state == STATE_STOPPED:
        scheduler.init_app(app)
        scheduler.add_job(
            func=tasks.batch_donation,
            trigger="interval",
            seconds=app.config["SCHEDULER_INTERVAL"],
            id="batch_donation",
            replace_existing=True,
        )
        scheduler.add_job(
            func=tasks.random_distribution,
            trigger="interval",
            seconds=app.config["SCHEDULER_INTERVAL"],
            id="random_distribution",
            replace_existing=True,
        )
        scheduler.start()

    return app
