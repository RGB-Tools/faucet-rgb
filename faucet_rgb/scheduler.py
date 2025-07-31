"""Scheduler module."""

import traceback
from typing import Sequence

import rgb_lib

from flask import Flask, current_app
from flask_apscheduler import APScheduler
from rgb_lib import Unspent, Wallet

from .database import Request, db, select_query, update_query
from .utils import (
    create_witness_utxos,
    get_logger,
    get_recipient,
    get_recipient_map_stats,
)

scheduler = APScheduler()


def get_app() -> Flask:
    """Get the Flask app from the scheduler.

    This will only work once the scheduler has been initialized.
    The returned app is typed as Flask for convenience.
    """
    assert scheduler.app
    return scheduler.app


def send_next_batch(spare_utxos: list[Unspent]):
    """Send the next batch of queued requests.

    If the SINGLE_ASSET_SEND option is True, only send a single asset per
    batch, which should help to:
    - keep asset histories separate
    - keep number of unspendable UTXOs low
    """
    with get_app().app_context():
        logger = get_logger(__name__)
        cfg = current_app.config

        # get requests to be processed
        stmt = select_query(Request.status == 20)
        pending_reqs = db.session.scalars(stmt).all()
        if not pending_reqs:
            print("no pending reqs")
            return  # no requests to process
        if cfg["SINGLE_ASSET_SEND"]:
            # filter for asset ID of oldest request
            oldest_req = pending_reqs[0]
            stmt = stmt.where(Request.asset_id == oldest_req.asset_id)
            pending_reqs = db.session.scalars(stmt).all()

        # get asset set
        asset_id_set = {r.asset_id for r in pending_reqs}

        # prepare recipient map
        recipient_map = {}
        for asset_id in asset_id_set:
            # get list of recipients that need to receive this asset
            recipient_list = []
            for req in pending_reqs:
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
        _try_send(pending_reqs, cfg, recipient_map, stats)


def _try_send(reqs: Sequence[Request], cfg, recipient_map, stats):
    """Try to send."""
    with get_app().app_context():
        logger = get_logger(__name__)
        wallet: Wallet = cfg["WALLET"]
        try:
            # set request status to "processing"
            logger.info("sending batch donation")
            idxs = [req.idx for req in reqs]
            db.session.execute(update_query(Request.idx.in_(idxs)).values(status=30))
            db.session.commit()

            # send assets
            txid = wallet.send(
                cfg["ONLINE"],
                recipient_map,
                True,
                cfg["FEE_RATE"],
                cfg["MIN_CONFIRMATIONS"],
                False,
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
                db.session.execute(update_query(Request.idx == req.idx).values(status=40))
            db.session.commit()
        except rgb_lib.RgbLibError.InsufficientAllocationSlots:
            logger.error("Failed to send: not enough allocation slots")
        except rgb_lib.RgbLibError.InsufficientAssignments:
            logger.error("Failed to send: not enough assignments")
        except Exception:  # pylint: disable=broad-exception-caught
            # log any other error, including traceback
            logger.error("Failed to send: unexpected")
            logger.error(traceback.format_exc())
