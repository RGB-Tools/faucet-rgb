"""fixtures for tests"""

import os
import shutil

import pytest

from tests.utils import (
    create_test_app, get_test_datadir, get_test_name, prepare_assets)


def _default_app_prep(app):
    return prepare_assets(app, "group_1")


@pytest.fixture(name="get_app")
def fixture_get_app():
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
