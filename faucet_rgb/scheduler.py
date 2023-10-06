"""Scheduler module."""

import rgb_lib
from flask import current_app
from flask_apscheduler import APScheduler

from faucet_rgb.utils import get_logger

from .database import Request, db

scheduler = APScheduler()


def send_next_batch():
    """Send the next batch of queued requests.

    If the SINGLE_ASSET_SEND option is True, only send a single asset per
    batch, which should help to:
    - keep asset histories separate
    - keep number of unspendable UTXOs low
    """
    with scheduler.app.app_context():
        logger = get_logger(__name__)
        cfg = current_app.config

        # get requests to be processed
        pending_reqs = Request.query.filter_by(status=20)
        if cfg['SINGLE_ASSET_SEND']:
            # filter for asset ID of oldest request
            oldest_req = Request.query.filter_by(status=20).first()
            pending_reqs = Request.query.filter(
                Request.status == 20, Request.asset_id == oldest_req.asset_id)
        reqs = pending_reqs.all()

        # get asset set
        asset_id_set = {r.asset_id for r in reqs}

        # prepare recipient map
        recipient_map = {}
        for asset_id in asset_id_set:
            # get list of recipients that need to receive this asset
            recipient_list = []
            for req in reqs:
                if req.asset_id == asset_id:
                    recipient_list.append(
                        rgb_lib.Recipient(req.blinded_utxo, None, req.amount,
                                          cfg['TRANSPORT_ENDPOINTS']))
            recipient_map[asset_id] = recipient_list

        # try sending
        try:
            # set request status to "processing"
            logger.info('sending batch donation')
            for req in reqs:
                Request.query.filter_by(idx=req.idx).update({"status": 30})
            db.session.commit()  # pylint: disable=no-member

            # send assets
            txid = cfg['WALLET'].send(cfg['ONLINE'], recipient_map, True,
                                      cfg['FEE_RATE'],
                                      cfg['MIN_CONFIRMATIONS'])
            logger.info('batch donation sent with TXID: %s', txid)

            # update status for served requests
            for req in reqs:
                Request.query.filter_by(idx=req.idx).update({'status': 40})
            db.session.commit()  # pylint: disable=no-member
        except (rgb_lib.RgbLibError.InsufficientSpendableAssets,
                rgb_lib.RgbLibError.InsufficientTotalAssets):
            logger.error('Not enough assets, send failed')
        except Exception as err:  # pylint: disable=broad-exception-caught
            # log any other error
            logger.error('Failed to send assets %s', err)
