"""Scheduler tasks module."""

import random
from datetime import datetime, timezone

from flask import current_app

from faucet_rgb.settings import DistributionMode

from .database import Request, db
from .scheduler import scheduler, send_next_batch
from .utils import get_current_timestamp, get_logger


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
        online = current_app.config['ONLINE']
        wallet = current_app.config['WALLET']
        min_requests = current_app.config['MIN_REQUESTS']
        max_wait_minutes = current_app.config['MAX_WAIT_MINUTES']
        single_asset = current_app.config['SINGLE_ASSET_SEND']

        # refresh pending transfers
        try:
            wallet.refresh(online, None, [])
        except Exception as err:  # pylint: disable=broad-exception-caught
            logger.error('error refreshing transfers: %s', repr(err))

        # reset status for requests left being processed to "pending"
        Request.query.filter_by(status=30).update({'status': 20})
        db.session.commit()  # pylint: disable=no-member

        # checks
        request_thresh_reached = False
        enough_time_elapsed = False
        pending_requests = Request.query.filter_by(status=20)
        if pending_requests.count() and single_asset:
            oldest_req = Request.query.filter_by(status=20).first()
            pending_requests = Request.query.filter(
                Request.status == 20, Request.asset_id == oldest_req.asset_id)
        # request count against configured threshold
        if pending_requests.count() >= min_requests:
            request_thresh_reached = True
        # elapsed time since oldest request
        if pending_requests.count():
            oldest_timestamp = pending_requests.first().timestamp
            if get_current_timestamp(
            ) - oldest_timestamp >= max_wait_minutes * 60:
                enough_time_elapsed = True

        if request_thresh_reached or enough_time_elapsed:
            send_next_batch()


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
        date_format = current_app.config['DATE_FORMAT']
        wallet = current_app.config['WALLET']

        now = datetime.now(timezone.utc)
        for group, val in current_app.config['ASSETS'].items():
            # skip if not random mode or request window has not closed yet
            dist_conf = current_app.config['ASSETS'][group].get('distribution')
            dist_mode = DistributionMode(dist_conf['mode'])
            if dist_mode != DistributionMode.RANDOM:
                continue
            req_win_close = dist_conf['params']['request_window_close']
            req_win_close = datetime.strptime(req_win_close, date_format)
            if now < req_win_close:
                continue

            for asset in val['assets']:
                asset_id = asset['asset_id']
                # get waiting requests for asset
                reqs = Request.query.filter_by(asset_id=asset_id,
                                               status=25).all()
                # get asset future balance (what we expect to be able to send)
                balance = wallet.get_asset_balance(asset_id).future
                # choose random requests and set them to pending status
                while balance > 0 and reqs:
                    req = random.choice(reqs)
                    Request.query.filter_by(idx=req.idx).update({'status': 20})
                    db.session.commit()  # pylint: disable=no-member
                    reqs.remove(req)
                    balance -= 1
                # set remaining requests to unmet status
                Request.query.filter_by(asset_id=asset_id,
                                        status=25).update({'status': 45})
                db.session.commit()  # pylint: disable=no-member
