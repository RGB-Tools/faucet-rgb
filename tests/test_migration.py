"""
Tests for asset-migration functionality
"""

import glob
import os
import shutil
import time

import pytest

from sqlalchemy import select

from faucet_rgb.database import Request, count_query, db, select_query
from faucet_rgb.scheduler import scheduler
from faucet_rgb.utils import get_logger
from tests.utils import (
    add_fake_request,
    check_receive_asset,
    check_requests_left,
    create_test_app,
    prepare_assets,
    prepare_user_wallets,
    wait_sched_process_pending,
)


def _app_preparation_1(app):
    """Prepare app for the first launch."""

    app = prepare_assets(app, "group_1")
    app = prepare_assets(app, "group_2")

    # set it to large number so that time-elapsed will be the only cause of the transfer
    app.config["MIN_REQUESTS"] = 10000
    # if this is shorter than SCHEDULER_INTERVAL, scheduler will abort the task before
    # it finishes and restarts the new one
    # if this is too long, the test have to wait for too long time
    app.config["MAX_WAIT_MINUTES"] = 10 / 60
    # batch sends per asset
    app.config["SINGLE_ASSET_SEND"] = True
    # we want this to be as short as possible to make sure that batch-sending
    # will happen ASAP when necessary, but if it is too short, background task
    # (tasks.batch_donation) will fail to complete the procedure and it
    # restarts
    # since `Wallet::send` takes quite a long time (more than 4 seconds)
    # for batch-sending, we had to make it longer than that
    app.config["SCHEDULER_INTERVAL"] = 8
    return app


def _create_migration_map_from_two_configs(old_asset_config, new_asset_config, group):
    new_asset_ids = [asset["asset_id"] for asset in new_asset_config[group]["assets"]]
    return {
        new_asset_ids[i]: asset["asset_id"]
        for i, asset in enumerate(old_asset_config[group]["assets"])
    }


def _get_app_preparation_2(old_asset_config):
    def _app_preparation_2(app):
        app = prepare_assets(app, "group_1")
        app = prepare_assets(app, "group_2")
        app = prepare_assets(app, "group_dummy")

        mig_map_group_1 = _create_migration_map_from_two_configs(
            old_asset_config, app.config["ASSETS"], "group_1"
        )
        mig_map_group_2 = _create_migration_map_from_two_configs(
            old_asset_config, app.config["ASSETS"], "group_2"
        )
        app.config["ASSET_MIGRATION_MAP"] = mig_map_group_1 | mig_map_group_2
        return app

    return _app_preparation_2


def _assure_no_pending_request(app):
    """Wait until all requests are served.

    Wait for max 60 seconds for the background scheduler to run and set all
    request statuses to 40 (served).
    """
    logger = get_logger(__name__)
    logger.info("waiting for requests to be served...")
    retry = 0
    max_retry = 20
    app.config["WALLET"].create_utxos(
        app.config["ONLINE"],
        True,
        None,
        app.config["UTXO_SIZE"],
        app.config["FEE_RATE"],
        False,
    )
    while True:
        retry = retry + 1
        # abort the test after 60 seconds
        if retry >= max_retry:
            pytest.fail(
                "Test failed! Background scheduler did not "
                "set request status to 40 (served) for all requests"
            )
        with app.app_context():
            pending_requests = db.session.scalar(count_query(Request.status == 40))
            if not pending_requests:
                logger.info("all requests served")
                break
        time.sleep(3)


def test_migration(get_app):  # pylint: disable=too-many-statements
    """Test migration for the following cases.

    - User0: User received an old asset.
             > Request with no group ... must receive a random asset from a non-migration group.
             > Request with migration group ... must receive the corresponding migrated asset.
    - User1: User with no old asset.
             > Request with no group ... must receive a random asset from a non-migration group.
             > Request with migration group ... must fail.
    - User2: User received 2 old assets.
             > Request with no group ... must receive an asset from a non-migration group.
             > Request with migration group ... must receive the corresponding migrated asset.
    - User3: User requested an old asset but didn't receive it.
             > Pending request will be updated and re-interpreted as a request to the new asset.

    The following groups are considered in the test.

    - group_1: Assets being migrated. For User0,2.
    - group_2: Assets being migrated. For User2.
    - group_dummy: New group which is added after migration (a.k.a. non-migration group).
    """

    app = get_app(_app_preparation_1)
    assert not app.config["ASSET_MIGRATION_CACHE"]
    assert app.config["NON_MIGRATION_GROUPS"] == {"group_1", "group_2"}

    # pause the scheduler so it doesn't process pending requests
    scheduler.pause()

    # prepare user wallets
    users = prepare_user_wallets(app, 4)

    # user 0,2 have requested assets before migration
    # user 2 also has an asset from group_2
    add_fake_request(app, users[0], "group_1", 40)
    add_fake_request(app, users[2], "group_1", 40)
    add_fake_request(app, users[2], "group_2", 40)

    # user 3 requests asset before migration, but does not actually receive it
    add_fake_request(app, users[3], "group_1", 20)

    # -- restart app from scratch, configure new groups + migration
    print("restarting from scratch + configuring asset migration")
    scheduler.shutdown()
    while scheduler.running:
        time.sleep(1)
    wallet_dirs = glob.glob(os.path.join(app.config["DATA_DIR"], app.config["FINGERPRINT"]))
    for wallet_dir in wallet_dirs:
        shutil.rmtree(wallet_dir)

    old_asset_config = app.config["ASSETS"]
    app_preparation_2 = _get_app_preparation_2(old_asset_config)
    app = create_test_app(custom_app_prep=app_preparation_2)
    assert app.config["ASSET_MIGRATION_CACHE"].get("group_1") is not None
    assert app.config["ASSET_MIGRATION_CACHE"].get("group_2") is not None
    assert app.config["NON_MIGRATION_GROUPS"] == {"group_dummy"}

    new_group_1_asset_ids = [i["asset_id"] for i in app.config["ASSETS"]["group_1"]["assets"]]
    new_group_2_asset_ids = [i["asset_id"] for i in app.config["ASSETS"]["group_2"]["assets"]]
    dummy_asset_ids = [i["asset_id"] for i in app.config["ASSETS"]["group_dummy"]["assets"]]

    # check user 3 pending request is updated with the new (migrated) asset id
    with app.app_context():
        stmt = select_query(Request.wallet_id == users[3]["xpub"], Request.status != 40)
        user3_requests = db.session.scalars(stmt).all()
        assert len(user3_requests) == 1, "must have only one pending request"
        req = user3_requests[0]
        assert req.asset_id in new_group_1_asset_ids, "must migrate to new asset on startup"
    # the pending request has been updated > 0 requests_left for group_1
    check_requests_left(app, users[3]["xpub"], {"group_1": 0, "group_2": 0, "group_dummy": 1})

    # user 0 has not yet migrated group_1 > 1 request left
    # did not have group_2 migration > 0 requests left
    # has not yet requested from group_dummy > 1 request left
    check_requests_left(app, users[0]["xpub"], {"group_1": 1, "group_2": 0, "group_dummy": 1})
    # no group specified > send a random asset (from non-migration group)
    check_receive_asset(app, users[0], None, 200, dummy_asset_ids)
    # second request for non-migration group not allowed
    check_requests_left(app, users[0]["xpub"], {"group_1": 1, "group_2": 0, "group_dummy": 0})
    check_receive_asset(app, users[0], None, 403)
    # group_1 specified > send migrated asset
    check_receive_asset(app, users[0], "group_1", 200, new_group_1_asset_ids)
    # second request for same migration group not allowed
    check_requests_left(app, users[0]["xpub"], {"group_1": 0, "group_2": 0, "group_dummy": 0})
    check_receive_asset(app, users[0], "group_1", 403)
    # reqeust for group_2 (user doesn't have an old request for it) > deny
    check_receive_asset(app, users[0], "group_2", 403)

    # user 1 has no old requests for migration groups > 0 requsts left for both
    # has not yet requested from group_dummy > 1 request left
    check_requests_left(app, users[1]["xpub"], {"group_1": 0, "group_2": 0, "group_dummy": 1})
    # no group specified > send a random asset (from non-migration group)
    check_receive_asset(app, users[1], None, 200, dummy_asset_ids)
    # second request for non-migration group not allowed
    check_requests_left(app, users[1]["xpub"], {"group_1": 0, "group_2": 0, "group_dummy": 0})
    check_receive_asset(app, users[1], None, 403)

    # user 2 has old requests for both migration groups > 1 request left each
    # has not yet requested from group_dummy > 1 request left
    check_requests_left(app, users[2]["xpub"], {"group_1": 1, "group_2": 1, "group_dummy": 1})
    # no group specified > send a random asset (from non-migration group)
    check_receive_asset(app, users[2], None, 200, dummy_asset_ids)
    # second request for non-migration group not allowed
    check_requests_left(app, users[2]["xpub"], {"group_1": 1, "group_2": 1, "group_dummy": 0})
    check_receive_asset(app, users[2], None, 403)
    # group_1 specified > send migrated asset
    check_receive_asset(app, users[2], "group_1", 200, new_group_1_asset_ids)
    # second request for same migration group not allowed
    check_requests_left(app, users[2]["xpub"], {"group_1": 0, "group_2": 1, "group_dummy": 0})
    check_receive_asset(app, users[2], "group_1", 403)
    # group_2 specified > send migrated asset
    check_receive_asset(app, users[2], "group_2", 200, new_group_2_asset_ids)
    # second request for same migration group not allowed
    check_requests_left(app, users[2]["xpub"], {"group_1": 0, "group_2": 0, "group_dummy": 0})
    check_receive_asset(app, users[2], "group_2", 403)

    # wait for scheduler to process requests
    wait_sched_process_pending(app)

    # -- restart app (no configuration changes)
    print("restarting with no configuration changes")
    scheduler.shutdown()
    while scheduler.running:
        time.sleep(1)
    app = create_test_app(config=app.config)
    assert app.config["ASSET_MIGRATION_CACHE"].get("group_1") is not None
    assert app.config["ASSET_MIGRATION_CACHE"].get("group_2") is not None
    assert app.config["NON_MIGRATION_GROUPS"] == {"group_dummy"}

    # user 0 has now migrated group_1 > 0 requests left
    # did not have group_2 migration > 0 requests left
    # has already requested from group_dummy > 0 requests left
    check_requests_left(app, users[0]["xpub"], {"group_1": 0, "group_2": 0, "group_dummy": 0})

    # user 1 did not have group_1 migration > 0 requests left
    # did not have group_2 migration > 0 requests left
    # has already requested from group_dummy > 0 requests left
    check_requests_left(app, users[1]["xpub"], {"group_1": 0, "group_2": 0, "group_dummy": 0})

    # user 2 has now migrated group_1 > 0 requests left
    # has now migrated group_2 > 0 requests left
    # has already requested from group_dummy > 0 requests left
    check_requests_left(app, users[0]["xpub"], {"group_1": 0, "group_2": 0, "group_dummy": 0})

    # user 3 has now migrated group_1 > 0 requests left
    # did not have group_2 migration > 0 requests left
    # has not requested from group_dummy yet > 1 request left
    check_requests_left(app, users[3]["xpub"], {"group_1": 0, "group_2": 0, "group_dummy": 1})

    # -- restart again with no asset migration
    print("restarting with migration no more configured")
    scheduler.shutdown()
    while scheduler.running:
        time.sleep(1)
    config = app.config
    config["ASSETS"].pop("group_1")
    config["ASSETS"].pop("group_2")
    config["ASSET_MIGRATION_MAP"] = None
    app = create_test_app(config=config)
    assert not app.config["ASSET_MIGRATION_CACHE"]
    assert app.config["NON_MIGRATION_GROUPS"] == {"group_dummy"}

    # user 0 has already requested from group_dummy > 0 requests left
    check_requests_left(app, users[0]["xpub"], {"group_dummy": 0})

    # user 1 has already requested from group_dummy > 0 requests left
    check_requests_left(app, users[1]["xpub"], {"group_dummy": 0})

    # user 2 has already requested from group_dummy > 0 requests left
    check_requests_left(app, users[0]["xpub"], {"group_dummy": 0})

    # user 3 has not requested from group_dummy yet > 1 request left
    check_requests_left(app, users[3]["xpub"], {"group_dummy": 1})
