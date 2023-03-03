"""
Tests for asset-migration functionality
"""

import glob
import os
import time

import pytest

from faucet_rgb import Request
from faucet_rgb.scheduler import scheduler
from faucet_rgb.utils import get_logger
from tests import (  # pylint:disable=unused-import
    fixture_get_app, get_test_name)
from tests.utils import (
    check_receive_asset, check_requests_left, create_test_app, prepare_assets,
    prepare_user_wallets)


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


def _create_migration_map_from_two_configs(old_asset_config, new_asset_config,
                                           group):
    new_asset_ids = [
        asset["asset_id"] for asset in new_asset_config[group]["assets"]
    ]
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
            old_asset_config, app.config["ASSETS"], "group_1")
        mig_map_group_2 = _create_migration_map_from_two_configs(
            old_asset_config, app.config["ASSETS"], "group_2")
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
    app.config["WALLET"].create_utxos(app.config["ONLINE"], True, None, None,
                                      app.config["FEE_RATE"])
    while True:
        retry = retry + 1
        # abort the test after 60 seconds
        if retry >= max_retry:
            pytest.fail("Test failed! Background scheduler did not "
                        "set request status to 40 (served) for all requests")
        with app.app_context():
            pending_request = Request.query.filter(
                Request.status != 40).count()
            if not pending_request:
                logger.info("all requests served")
                break
        time.sleep(3)


def test_migration(get_app):
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
    - group_dummy: New group which is added after migration(a.k.a. non-migration group).
    """

    app = get_app(_app_preparation_1)

    users = prepare_user_wallets(app, 4)

    # user 0,2 have requested asset before migration
    check_receive_asset(app, users[0], "group_1")
    check_receive_asset(app, users[2], "group_1")
    check_receive_asset(app, users[2],
                        "group_2")  # user 2 also has an asset from group_2

    _assure_no_pending_request(app)

    # stop for a while since we want to test with a pending request
    scheduler.pause()

    # user 3 requests asset before migration, but not actually received it
    # the request status for it must NOT be 40 (= "served")
    check_receive_asset(app, users[3], "group_1")

    # -- restart app with all assets removed --
    matches = glob.glob(os.path.join(app.config["DATA_DIR"], "*", "rgb_db"))
    for match in matches:
        os.remove(match)

    old_asset_config = app.config["ASSETS"]
    custom_asset_preparation = _get_app_preparation_2(old_asset_config)
    app = create_test_app(get_test_name(), custom_asset_preparation)

    new_group_1_asset_ids = [
        i["asset_id"] for i in app.config["ASSETS"]["group_1"]["assets"]
    ]
    new_group_2_asset_ids = [
        i["asset_id"] for i in app.config["ASSETS"]["group_2"]["assets"]
    ]
    dummy_asset_ids = [
        i["asset_id"] for i in app.config["ASSETS"]["group_dummy"]["assets"]
    ]

    # -- --

    # check (pending) request from user 3 is updated as a request for migrated asset id
    with app.app_context():
        user3_requests: Request = Request.query.filter(
            Request.wallet_id == users[3]["xpub"], Request.status != 40).all()
        assert len(user3_requests) == 1, "must have only one pending request"
        req = user3_requests[0]
        assert (
            req.asset_id
            in new_group_1_asset_ids), "must migrate to new asset on startup"
    # the pending request will be updated as a request for the new asset_id
    # thus requests_left for the group_1 will be 0
    check_requests_left(app, users[3]["xpub"], {
        "group_1": 0,
        "group_2": 0,
        "group_dummy": 1
    })

    # for users those have an old asset in group_1,
    # they can request a migration, thus requests_left for group_1 must be 1
    # they do not have an old asset in group_2, Thus request_left must be 0
    check_requests_left(app, users[0]["xpub"], {
        "group_1": 1,
        "group_2": 0,
        "group_dummy": 1
    })

    # must send a random asset (from non-migration group) when no group is specified
    check_receive_asset(app, users[0], None, 200, dummy_asset_ids)
    # second request for non-migration group is not allowed
    check_requests_left(app, users[0]["xpub"], {
        "group_1": 1,
        "group_2": 0,
        "group_dummy": 0
    })
    check_receive_asset(app, users[0], None, 403)

    # even the user has an asset from non-migration group, it should not affect
    # the fact that he can still migrate
    check_requests_left(app, users[0]["xpub"], {
        "group_1": 1,
        "group_2": 0,
        "group_dummy": 0
    })
    # must send a new asset when requested with the group_id for waiting migration
    check_receive_asset(app, users[0], "group_1", 200, new_group_1_asset_ids)
    # after migration request, requests_left for migration group must be 0
    check_requests_left(app, users[0]["xpub"], {
        "group_1": 0,
        "group_2": 0,
        "group_dummy": 0
    })
    # second request for migration group is not allowed
    check_receive_asset(app, users[0], "group_1", 403)

    # should fail to request an asset for migration group which
    # the user does not have an old asset
    check_receive_asset(app, users[0], "group_2", 403)
    # --- ---

    # --- case 2: users without old asset ---
    check_requests_left(app, users[1]["xpub"], {
        "group_1": 0,
        "group_2": 0,
        "group_dummy": 1
    })

    # must send a random asset from non-migration group
    # when they did not specify a group_id
    check_receive_asset(app, users[1], None, 200, dummy_asset_ids)

    # second request for non-migration group is not allowed
    check_requests_left(app, users[1]["xpub"], {
        "group_1": 0,
        "group_2": 0,
        "group_dummy": 0
    })
    check_receive_asset(app, users[1], None, 403)

    # must not send a new asset for new users if the group_id is in
    # a migration group
    check_receive_asset(app, users[1], "group_1", 403)
    # --- ---

    # --- case 3: user received 2 old asset, one in group_1, another in group_2 ---
    check_requests_left(app, users[2]["xpub"], {
        "group_1": 1,
        "group_2": 1,
        "group_dummy": 1
    })

    # must send a random asset (from non-migration group) when no group is specified
    check_receive_asset(app, users[2], None, 200, dummy_asset_ids)
    check_requests_left(app, users[2]["xpub"], {
        "group_1": 1,
        "group_2": 1,
        "group_dummy": 0
    })

    # must send a new asset when requested with the group_id waiting for migration
    check_receive_asset(app, users[2], "group_1", 200, new_group_1_asset_ids)

    # after issuance, request_left will be 0 only for that group
    check_requests_left(app, users[2]["xpub"], {
        "group_1": 0,
        "group_2": 1,
        "group_dummy": 0
    })

    # and fails to send new asset again
    check_receive_asset(app, users[2], "group_1", 403)

    # same for group_2
    check_receive_asset(app, users[2], "group_2", 200, new_group_2_asset_ids)
    check_requests_left(app, users[2]["xpub"], {
        "group_1": 0,
        "group_2": 0,
        "group_dummy": 0
    })
    check_receive_asset(app, users[2], "group_2", 403)
