"""Scheduler tasks module."""

from flask import current_app

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
    # get configuration variables
    with scheduler.app.app_context():
        logger = get_logger(__name__)
        online = current_app.config['ONLINE']
        wallet = current_app.config['WALLET']
        min_requests = current_app.config['MIN_REQUESTS']
        max_wait_minutes = current_app.config['MAX_WAIT_MINUTES']
        single_asset = current_app.config['SINGLE_ASSET_SEND']

        # refresh pending transfers
        try:
            wallet.refresh(online, None, [])
        except Exception as err:
            logger.error('error refreshing transfers: %s', repr(err))

        # reset status for requests left being processed to "pending"
        Request.query.filter_by(status=30).all()
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
            oldest_timestamp = pending_requests.all()[0].timestamp
            if get_current_timestamp(
            ) - oldest_timestamp >= max_wait_minutes * 60:
                enough_time_elapsed = True

        if request_thresh_reached or enough_time_elapsed:
            send_next_batch()
