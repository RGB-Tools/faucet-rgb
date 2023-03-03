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
    - keep consignment sizes down
    - workaround the PSBT key error issue on mutliple assets per UTXO
    """
    with scheduler.app.app_context():
        logger = get_logger(__name__)
        cfg = {}
        cfg['online'] = current_app.config['ONLINE']
        cfg['wallet'] = current_app.config['WALLET']
        cfg['fee_rate'] = current_app.config['FEE_RATE']
        cfg['req_number'] = current_app.config['MIN_REQUESTS']
        cfg['single_asset'] = current_app.config['SINGLE_ASSET_SEND']

        # request selection
        req_batch = Request.query.filter_by(status=20).slice(
            0, cfg['req_number'])
        if cfg['single_asset']:
            oldest_req = Request.query.filter_by(status=20).first()
            req_batch = Request.query.filter(
                Request.status == 20,
                Request.asset_id == oldest_req.asset_id).slice(
                    0, cfg['req_number'])
        reqs = req_batch.all()

        # get asset set
        asset_id_set = {r.asset_id for r in reqs}

        # prepare recipient map
        recipient_map = {}
        for asset_id in asset_id_set:
            # get list of blinded UTXOs that need to receive this asset
            recipient_list = []
            for req in reqs:
                if req.asset_id == asset_id:
                    recipient_list.append(
                        rgb_lib.Recipient(
                            req.blinded_utxo, req.amount,
                            current_app.config['CONSIGNMENT_ENDPOINTS']))
            recipient_map[asset_id] = recipient_list

        # try sending
        try:
            # set request status to "processing"
            logger.info('sending batch donation')
            for req in reqs:
                Request.query.filter_by(idx=req.idx).update({"status": 30})
            db.session.commit()  # pylint: disable=no-member

            # send assets
            txid = cfg['wallet'].send(cfg['online'], recipient_map, True,
                                      cfg['fee_rate'])
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
