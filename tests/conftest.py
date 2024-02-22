"""fixtures for tests"""

import os
import shutil
import subprocess

import pytest
from apscheduler.schedulers import SchedulerNotRunningError

from faucet_rgb.scheduler import scheduler
from tests.utils import create_test_app, get_test_datadir, prepare_assets


def _default_app_prep(app):
    return prepare_assets(app, "group_1")


@pytest.fixture()
def get_app():
    """Fixture to get running faucet_rgb app with default settings.

    DATA_DIR for the app is configured as `test_data/<method_name>`.
    By default, both NIA and CFA assets are issued (1 asset for each type)
    with the group name "group_1"

    Args:
        custom_app_prep (function): Function which will be run after the app
            initialization. It must issue assets and set config for the app.
            Takes an app as an argument and returns the updated app.
            By default it just issues NIA and CFA assets with the group named
            "group_1".
    """

    def _get_app(custom_app_prep=_default_app_prep):
        datadir = get_test_datadir()
        if os.path.exists(datadir):
            shutil.rmtree(datadir)
        os.makedirs(datadir, exist_ok=True)

        return create_test_app(custom_app_prep=custom_app_prep)

    return _get_app


@pytest.fixture(autouse=True, scope="function")
def shutdown_scheduler():
    """Shutdown the scheduler after each test."""
    yield
    print("shutting down scheduler...")
    try:
        scheduler.shutdown()
    except SchedulerNotRunningError:
        print("could not shut down the scheduler (not running)")


@pytest.fixture(autouse=True, scope="session")
def start_services():
    """Start/stop services required for tests to run."""
    subprocess.run(
        ["docker/services.sh", "start"],
        capture_output=True,
        timeout=10000,
        check=True,
    )
    yield
    subprocess.run(
        ["docker/services.sh", "stop"],
        capture_output=True,
        timeout=10000,
        check=True,
    )
