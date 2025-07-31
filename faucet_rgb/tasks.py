"""Scheduler tasks module."""

import contextlib
import random

from datetime import datetime

import rgb_lib

from flask import current_app
from rgb_lib import Wallet

from .database import Request, count_query, db, select_query, update_query
from .scheduler import get_app, send_next_batch
from .settings import DistributionMode
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
    with get_app().app_context():
        # get configuration variables
        logger = get_logger(__name__)
        cfg = current_app.config
        wallet: Wallet = cfg["WALLET"]

        # refresh pending transfers
        try:
            wallet.refresh(cfg["ONLINE"], None, [], False)
        except Exception as err:  # pylint: disable=broad-exception-caught
            logger.error("error refreshing transfers: %s", repr(err))

        # reset status for requests left being processed to "pending"
        db.session.execute(update_query(Request.status == 30).values(status=20))
        db.session.commit()

        # make sure colorable UTXOs are available
        spare_utxos = get_spare_utxos(cfg)
        if len(spare_utxos) < cfg["SPARE_UTXO_THRESH"]:
            with contextlib.suppress(rgb_lib.RgbLibError.AllocationsAlreadyAvailable):
                created = wallet.create_utxos(
                    cfg["ONLINE"],
                    True,
                    cfg["SPARE_UTXO_NUM"],
                    cfg["UTXO_SIZE"],
                    cfg["FEE_RATE"],
                    False,
                )
                logger.info("%s UTXOs created", created)

        # checks
        request_thresh_reached = False
        enough_time_elapsed = False
        pending_reqs_count = db.session.scalar(count_query(Request.status == 20))
        oldest_req = db.session.scalars(select_query(Request.status == 20).limit(1)).first()
        if pending_reqs_count and cfg["SINGLE_ASSET_SEND"]:
            assert oldest_req  # pending_reqs_count is poisitive
            pending_reqs_count = db.session.scalar(
                count_query(Request.asset_id == oldest_req.asset_id)
            )
        # request count against configured threshold
        if pending_reqs_count >= cfg["MIN_REQUESTS"]:
            request_thresh_reached = True
        # elapsed time since oldest request
        if pending_reqs_count:
            assert oldest_req  # pending_reqs_count is poisitive
            oldest_timestamp = oldest_req.timestamp
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
    with get_app().app_context():
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
                reqs = list(
                    db.session.scalars(
                        select_query(Request.asset_id == asset_id, Request.status == 25)
                    ).all()
                )
                # get asset future balance (what we expect to be able to send)
                balance = cfg["WALLET"].get_asset_balance(asset_id).future
                count = 0
                # choose random requests and set them to pending status
                while balance > 0 and reqs:
                    req = random.choice(reqs)
                    db.session.execute(update_query(Request.idx == req.idx).values(status=20))
                    db.session.commit()
                    reqs.remove(req)
                    balance -= 1
                    count += 1
                if count > 0:
                    logger.info("set %s requests as pending for asset %s", count, asset_id)
                # note: update statements return a CursorResult that have a rowcount
                reqs_unmet = db.session.execute(
                    update_query(Request.asset_id == asset_id, Request.status == 25).values(
                        status=45
                    )
                ).rowcount  # type: ignore[attr-defined]
                db.session.commit()
                if reqs_unmet > 0:
                    logger.info("set %s requests as unmet for asset %s", reqs_unmet, asset_id)
