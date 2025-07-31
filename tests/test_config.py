"""Tests for APIs."""

from datetime import datetime, timedelta

from faucet_rgb import exceptions
from faucet_rgb.database import count_query, db, select_query
from tests.utils import (
    check_receive_asset,
    prepare_assets,
    prepare_user_wallets,
    random_dist_mode,
    refresh_and_check_settled,
    wait_sched_process_pending,
)


def _app_prep_cfg_no_dist(app):
    """Prepare app with empty distribution configuration."""
    dist_mode = {}
    app = prepare_assets(app, "group_1", dist_mode=dist_mode)
    return app


def _app_prep_cfg_no_dist_mode(app):
    """Prepare app with missing distribution mode."""
    dist_mode = {"unknown": -1}
    app = prepare_assets(app, "group_1", dist_mode=dist_mode)
    return app


def _app_prep_cfg_bad_dist_mode(app):
    """Prepare app with unsupported distribution mode."""
    dist_mode = {"mode": 3}
    app = prepare_assets(app, "group_1", dist_mode=dist_mode)
    return app


def _app_prep_cfg_random_no_params(app):
    """Prepare app with random distribution mode but no params."""
    dist_mode = {"mode": 2}
    app = prepare_assets(app, "group_1", dist_mode=dist_mode)
    return app


def _app_prep_cfg_random_bad_params(app):
    """Prepare app with random distribution mode but bad params."""
    now = datetime.now()
    req_win_open = now + timedelta(seconds=30)
    dist_mode = random_dist_mode(
        app.config, now + timedelta(seconds=30), req_win_open + timedelta(minutes=1)
    )
    app = prepare_assets(app, "group_1", dist_mode=dist_mode)
    return app


def _app_prep_cfg_random_bad_req_win(app):
    """Prepare app with random distribution mode but bad request window."""
    now = datetime.now()
    date_fmt = app.config["DATE_FORMAT"]
    req_win_open = now + timedelta(days=1)
    req_win_close = now - timedelta(days=1)
    dist_mode = {
        "mode": 2,
        "random_params": {
            "request_window_open": datetime.strftime(req_win_open, date_fmt),
            "request_window_close": datetime.strftime(req_win_close, date_fmt),
        },
    }
    app = prepare_assets(app, "group_1", dist_mode=dist_mode)
    return app


def _app_prep_0conf(app):
    """Prepare app for the first launch."""
    app = prepare_assets(app, "group_1")
    app.config["MIN_CONFIRMATIONS"] = 0
    return app


def _app_prep_missing_asset(app):
    """Prepare app with a missing asset."""
    group_name = "group_1"
    app = prepare_assets(app, group_name=group_name)
    asset_1_id = app.config["ASSETS"][group_name]["assets"][0]["asset_id"]
    # swap the last two characters to change the asset ID
    assert asset_1_id[-2] != asset_1_id[-1]
    asset_1_id = asset_1_id[:-2] + asset_1_id[-1] + asset_1_id[-2]
    app.config["ASSETS"][group_name]["assets"][0]["asset_id"] = asset_1_id
    return app


def test_0_conf(get_app):
    """Test MIN_CONFIRMATIONS set to 0."""
    app = get_app(_app_prep_0conf)
    client = app.test_client()

    # request an asset
    user = prepare_user_wallets(app, 1)[0]
    check_receive_asset(app, user, None, 200)
    with app.app_context():
        request_count = db.session.scalar(count_query())
        assert request_count == 1
        request = db.session.scalars(select_query()).one()
    asset_id = request.asset_id
    wait_sched_process_pending(app)
    # check send transfer is settled after one refresh (no mining)
    refresh_and_check_settled(client, app.config, asset_id)


def test_cfg_no_dist(get_app):
    """Test configuration with missing distribution key."""
    try:
        get_app(_app_prep_cfg_no_dist)
    except exceptions.ConfigurationError as err:
        assert len(err.errors) == 1
        assert "missing distribution for group" in err.errors[0]


def test_cfg_no_dist_mode(get_app):
    """Test configuration with missing distribution mode."""
    try:
        get_app(_app_prep_cfg_no_dist_mode)
    except exceptions.ConfigurationError as err:
        assert len(err.errors) == 1
        assert "missing distribution mode" in err.errors[0]


def test_cfg_bad_dist_mode(get_app):
    """Test configuration with unsupported distribution mode."""
    try:
        get_app(_app_prep_cfg_bad_dist_mode)
    except exceptions.ConfigurationError as err:
        assert len(err.errors) == 1
        assert "not a valid DistributionMode" in err.errors[0]


def test_cfg_random_no_params(get_app):
    """Test configuration for random distribution mode with no params."""
    try:
        get_app(_app_prep_cfg_random_no_params)
    except exceptions.ConfigurationError as err:
        assert len(err.errors) == 1
        assert "missing distribution random params" in err.errors[0]


def test_cfg_random_bad_params(get_app):
    """Test configuration for random distribution mode with bad params."""
    try:
        get_app(_app_prep_cfg_random_bad_params)
    except exceptions.ConfigurationError as err:
        assert len(err.errors) == 2
        assert all("does not match format" in e for e in err.errors)


def test_cfg_random_bad_req_win(get_app):
    """Test configuration for random distribution mode with bad params."""
    try:
        get_app(_app_prep_cfg_random_bad_req_win)
    except exceptions.ConfigurationError as err:
        assert len(err.errors) == 1
        assert "not after open" in err.errors[0]


def test_cfg_missing_asset(get_app):
    """Test configuration with missing asset."""
    try:
        get_app(_app_prep_missing_asset)
    except exceptions.ConfigurationError as err:
        assert len(err.errors) == 1
        assert "configured asset with ID" in err.errors[0]
        assert "not found" in err.errors[0]
