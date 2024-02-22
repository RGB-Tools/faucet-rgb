"""Scheduler tasks module."""

import contextlib
import random
from datetime import datetime

import rgb_lib
from flask import current_app

from faucet_rgb.settings import DistributionMode

from .database import Request, db
from .scheduler import scheduler, send_next_batch
from .utils import get_current_timestamp, get_logger, get_spare_utxos


def batch_donation():
    """
    Batch donation task.

    First, refresh currently pending transfers so they can settle.
    Then, check if the minimum amount of recipients or the maximum waiting time
    have been reached. If so, send the next batch of asset donations.

    If the SINGLE_ASSET_SEND option is True, only consider a single asset. See
    the send_next_batch function for details.
    """
    with scheduler.app.app_context():
        # get configuration variables
        logger = get_logger(__name__)
        cfg = current_app.config

        # refresh pending transfers
        try:
            cfg["WALLET"].refresh(cfg["ONLINE"], None, [])
        except Exception as err:  # pylint: disable=broad-exception-caught
            logger.error("error refreshing transfers: %s", repr(err))

        # reset status for requests left being processed to "pending"
        Request.query.filter_by(status=30).update({"status": 20})
        db.session.commit()  # pylint: disable=no-member

        # make sure colorable UTXOs are available
        spare_utxos = get_spare_utxos(cfg)
        if len(spare_utxos) < cfg["SPARE_UTXO_THRESH"]:
            with contextlib.suppress(rgb_lib.RgbLibError.AllocationsAlreadyAvailable):
                created = cfg["WALLET"].create_utxos(
                    cfg["ONLINE"],
                    True,
                    cfg["SPARE_UTXO_NUM"],
                    cfg["UTXO_SIZE"],
                    cfg["FEE_RATE"],
                )
                logger.info("%s UTXOs created", created)

        # checks
        request_thresh_reached = False
        enough_time_elapsed = False
        pending_requests = Request.query.filter_by(status=20)
        if pending_requests.count() and cfg["SINGLE_ASSET_SEND"]:
            oldest_req = Request.query.filter_by(status=20).first()
            pending_requests = Request.query.filter(
                Request.status == 20, Request.asset_id == oldest_req.asset_id
            )
        # request count against configured threshold
        if pending_requests.count() >= cfg["MIN_REQUESTS"]:
            request_thresh_reached = True
        # elapsed time since oldest request
        if pending_requests.count():
            oldest_timestamp = pending_requests.first().timestamp
            if get_current_timestamp() - oldest_timestamp >= cfg["MAX_WAIT_MINUTES"] * 60:
                enough_time_elapsed = True

        if request_thresh_reached or enough_time_elapsed:
            send_next_batch(spare_utxos)


def random_distribution():
    """
    Random distribution task.

    Update requests for random distribution asset groups:
    - choose random requests from received ones and set them as pending
    - set remaining requests as unmet
    """
    with scheduler.app.app_context():
        # get configuration variables
        logger = get_logger(__name__)
        cfg = current_app.config

        now = datetime.now()
        for group, val in current_app.config["ASSETS"].items():
            # skip if not random mode or request window has not closed yet
            dist_conf = current_app.config["ASSETS"][group].get("distribution")
            dist_mode = DistributionMode(dist_conf["mode"])
            if dist_mode != DistributionMode.RANDOM:
                continue
            req_win_close = dist_conf["random_params"]["request_window_close"]
            req_win_close = datetime.strptime(req_win_close, cfg["DATE_FORMAT"])
            if now < req_win_close:
                continue

            for asset in val["assets"]:
                asset_id = asset["asset_id"]
                # get waiting requests for asset
                reqs = Request.query.filter_by(asset_id=asset_id, status=25).all()
                # get asset future balance (what we expect to be able to send)
                balance = cfg["WALLET"].get_asset_balance(asset_id).future
                count = 0
                # choose random requests and set them to pending status
                while balance > 0 and reqs:
                    req = random.choice(reqs)
                    Request.query.filter_by(idx=req.idx).update({"status": 20})
                    db.session.commit()  # pylint: disable=no-member
                    reqs.remove(req)
                    balance -= 1
                    count += 1
                if count > 0:
                    logger.info("set %s requests as pending for asset %s", count, asset_id)
                # set remaining requests to unmet status
                reqs_unmet = Request.query.filter_by(asset_id=asset_id, status=25).update(
                    {"status": 45}
                )
                if reqs_unmet > 0:
                    logger.info("set %s requests as unmet for asset %s", reqs_unmet, asset_id)
                db.session.commit()  # pylint: disable=no-member
