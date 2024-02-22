"""Scheduler module."""

import traceback

import rgb_lib
from flask import current_app
from flask_apscheduler import APScheduler

from faucet_rgb.utils import (
    create_witness_utxos,
    get_logger,
    get_recipient,
    get_recipient_map_stats,
)

from .database import Request, db

scheduler = APScheduler()


def send_next_batch(spare_utxos):
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
        if cfg["SINGLE_ASSET_SEND"]:
            # filter for asset ID of oldest request
            oldest_req = Request.query.filter_by(status=20).first()
            pending_reqs = Request.query.filter(
                Request.status == 20, Request.asset_id == oldest_req.asset_id
            )
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
                    recipient = get_recipient(req.invoice, req.amount, cfg)
                    recipient_list.append(recipient)
            recipient_map[asset_id] = recipient_list

        # batch stats
        stats = get_recipient_map_stats(recipient_map)

        # create additional UTXOs as needed
        created = create_witness_utxos(cfg, stats, spare_utxos)
        logger.info("%s additional UTXOs created", created)

        # try sending
        _try_send(reqs, cfg, recipient_map, stats)


def _try_send(reqs, cfg, recipient_map, stats):
    """Try to send."""
    with scheduler.app.app_context():
        logger = get_logger(__name__)
        try:
            # set request status to "processing"
            logger.info("sending batch donation")
            for req in reqs:
                Request.query.filter_by(idx=req.idx).update({"status": 30})
            db.session.commit()  # pylint: disable=no-member

            # send assets
            txid = cfg["WALLET"].send(
                cfg["ONLINE"],
                recipient_map,
                True,
                cfg["FEE_RATE"],
                cfg["MIN_CONFIRMATIONS"],
            )
            logger.info(
                "batch donation (%s assets, %s recipients total, %s witnesses) sent with TXID: %s",
                stats["assets"],
                stats["recipients"],
                stats["witnesses"],
                txid,
            )

            # update status for served requests
            for req in reqs:
                Request.query.filter_by(idx=req.idx).update({"status": 40})
            db.session.commit()  # pylint: disable=no-member
        except rgb_lib.RgbLibError.InsufficientAllocationSlots:
            logger.error("Failed to send: not enough allocation slots")
        except rgb_lib.RgbLibError.InsufficientSpendableAssets:
            logger.error("Failed to send: not enough spendable assets")
        except rgb_lib.RgbLibError.InsufficientTotalAssets:
            logger.error("Failed to send: not enough total assets")
        except Exception:  # pylint: disable=broad-exception-caught
            # log any other error, including traceback
            logger.error("Failed to send: unexpected")
            logger.error(traceback.format_exc())
