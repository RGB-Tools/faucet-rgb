"""Tests for APIs."""

from datetime import datetime, timedelta

from faucet_rgb import Request, exceptions
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


def _app_preparation_0conf(app):
    """Prepare app for the first launch."""
    app = prepare_assets(app, "group_1")
    app.config["MIN_CONFIRMATIONS"] = 0
    return app


def test_0_conf(get_app):
    """Test MIN_CONFIRMATIONS set to 0."""
    app = get_app(_app_preparation_0conf)
    client = app.test_client()

    # request an asset
    user = prepare_user_wallets(app, 1)[0]
    check_receive_asset(app, user, None, 200)
    with app.app_context():
        requests = Request.query
        assert requests.count() == 1
        request = requests.one()
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
