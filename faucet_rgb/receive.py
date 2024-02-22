"""Faucet blueprint to top-up funds."""

import json
import random
from datetime import datetime
from enum import Enum

import rgb_lib
from flask import Blueprint, current_app, jsonify, request

from faucet_rgb.settings import DistributionMode

from .database import Request, db
from .utils import get_current_timestamp, get_logger, get_rgb_asset, is_blinded_utxo
from .utils.wallet import is_walletid_valid

bp = Blueprint("receive", __name__, url_prefix="/receive")


class DenyReason(Enum):
    """Reason the request is being denied for."""

    ALREADY_REQUESTED = 1
    OUSTIDE_REQUEST_WINDOW = 2
    MIGRATION_COMPLETE = 3
    NOT_IN_MIGRATION_LIST = 4


REASON_MAP = {
    1: "already requested from group",
    2: "outside the request window",
    3: "migration complete",
    4: "not in migration list",
}


@bp.route("/config/<wallet_id>", methods=["GET"])
def config(wallet_id):
    """Return current faucet configuration.

    wallet_id must be a SHA256 hash

    returns:
    - faucet name
    - configured groups and for each one:
      - its label
      - how many requests to /receive/asset the given wallet_id has left
    """
    auth = request.headers.get("X-Api-Key")
    if auth != current_app.config["API_KEY"]:
        return jsonify({"error": "unauthorized"}), 401

    # check wallet_id is valid
    if not is_walletid_valid(wallet_id):
        return jsonify({"error": "invalied wallet ID"}), 403

    # drop requests in status "new" which are older than a couple minutes
    time_thresh = get_current_timestamp() - 120
    Request.query.filter(Request.status == 10, Request.timestamp < time_thresh).delete()
    db.session.commit()  # pylint: disable=no-member

    assets = current_app.config["ASSETS"]
    groups = {}
    for group_name, group_data in assets.items():
        (allowed, _reason) = _is_request_allowed(wallet_id, group_name)
        groups[group_name] = {
            "label": group_data["label"],
            "distribution": group_data["distribution"],
            "requests_left": 1 if allowed else 0,
        }
    return jsonify({"name": current_app.config["NAME"], "groups": groups})


@bp.route("/asset", methods=["POST"])
def request_rgb_asset():  # pylint: disable=too-many-return-statements
    """Request sending configured amount to the provided invoice.

    body data:
    - wallet_id: a sha256 hash
    - invoice: a valid RGB invoice
    - asset_group: (optional) group name to be used

    - a wallet_id cannot request from the same asset group more than once
    - each request is checked before saving to db to make sure it is allowed
    - valid requests are saved, processing is handled by scheduler jobs
    """
    logger = get_logger(__name__)

    # request checks and data extraction
    result = _receive_asset_checks(request, current_app.config)
    if result.get("error"):
        return jsonify({"error": result["error"]}), result["code"]
    data = result["data"]
    invoice = result["invoice"]

    # refuse witness requests if not allowed for network
    if current_app.config["NETWORK"] not in current_app.config[
        "WITNESS_ALLOWED_NETWORKS"
    ] and not is_blinded_utxo(invoice.invoice_data().recipient_id):
        return (
            jsonify(
                {"error": f"witness send not supported on {current_app.config['NETWORK']} network"}
            ),
            403,
        )

    # choose asset group
    configured_assets = current_app.config["ASSETS"]
    asset_group = data.get("asset_group")
    if asset_group and asset_group not in configured_assets:
        return jsonify({"error": "invalid asset group"}), 404
    asset = None
    if asset_group is None:
        # chose randomly from non-migration groups
        asset_group = random.choice(list(current_app.config["NON_MIGRATION_GROUPS"]))
    asset = random.choice(list(configured_assets[asset_group]["assets"]))

    # check if request is allowed
    (allowed, reason) = _is_request_allowed(data["wallet_id"], asset_group)
    if not allowed:
        return (
            jsonify(
                {
                    "error": f"wallet has no right to request an asset from group {asset_group}",
                    "reason": REASON_MAP[reason.value],
                }
            ),
            403,
        )

    # handle asset migration
    non_mig_groups = current_app.config["NON_MIGRATION_GROUPS"]
    is_mig_request = asset_group not in non_mig_groups
    if is_mig_request:
        # wallet is entitled to a migration > detect the asset to be sent
        mig_cache = current_app.config["ASSET_MIGRATION_CACHE"]
        asset = mig_cache[asset_group].get(data["wallet_id"])
        # remove the user (and possibly the whole group) from migration cache
        del mig_cache[asset_group][data["wallet_id"]]
        if not mig_cache[asset_group]:
            del mig_cache[asset_group]

    return _request_rgb_asset_core(data["wallet_id"], invoice, asset_group, asset, logger)


def _request_rgb_asset_core(wallet_id, invoice, asset_group, asset, logger):
    # add request to db so max requests check works right away (no double req)
    # pylint: disable=no-member
    recipient_id = invoice.invoice_data().recipient_id
    invoice_str = invoice.invoice_string()
    db.session.add(Request(wallet_id, recipient_id, invoice_str, asset_group, None, None))
    req = Request.query.filter(
        Request.wallet_id == wallet_id,
        Request.invoice == invoice_str,
        Request.asset_group == asset_group,
        Request.status == 10,
    )
    assert req.count() == 1
    req_idx = req.first().idx
    db.session.commit()
    # pylint: enable=no-member

    # prepare asset data
    rgb_asset, schema = get_rgb_asset(asset["asset_id"])
    if rgb_asset is None:
        return jsonify({"error": "internal error getting asset data"}), 500
    asset_data = {
        "asset_id": asset["asset_id"],
        "schema": schema,
        "amount": asset["amount"],
        "name": rgb_asset.name,
        "precision": rgb_asset.precision,
        "description": None,
        "ticker": None,
    }
    if hasattr(rgb_asset, "description"):
        asset_data["description"] = rgb_asset.description
    if hasattr(rgb_asset, "ticker"):
        asset_data["ticker"] = rgb_asset.ticker

    # update request on db: update status, set asset_id and amount
    new_status = 20
    dist_conf = current_app.config["ASSETS"][asset_group]["distribution"]
    dist_mode = DistributionMode(dist_conf["mode"])
    if dist_mode == DistributionMode.RANDOM:
        new_status = 25
    # pylint: disable=no-member
    logger.debug(
        "setting request %s: asset_id %s, amount %s, status %s",
        req_idx,
        asset["asset_id"],
        asset["amount"],
        new_status,
    )
    Request.query.filter_by(idx=req_idx).update(
        {"status": new_status, "asset_id": asset["asset_id"], "amount": asset["amount"]}
    )
    db.session.commit()
    # pylint: enable=no-member

    return jsonify(
        {
            "asset": asset_data,
            "distribution": dist_conf,
        }
    )


def _is_request_allowed(wallet_id, group_name):
    """Return if a request should be allowed or denied."""
    # deny request if user has already placed a request for this group
    reqs = Request.query.filter(
        Request.wallet_id == wallet_id, Request.asset_group == group_name
    ).count()
    if reqs:
        return (False, DenyReason.ALREADY_REQUESTED)

    # deny based on distribution mode
    dist_conf = current_app.config["ASSETS"][group_name]["distribution"]
    dist_mode = DistributionMode(dist_conf["mode"])
    if dist_mode == DistributionMode.RANDOM:
        req_win_open = dist_conf["random_params"]["request_window_open"]
        req_win_close = dist_conf["random_params"]["request_window_close"]
        date_format = current_app.config["DATE_FORMAT"]
        req_win_open = datetime.strptime(req_win_open, date_format)
        req_win_close = datetime.strptime(req_win_close, date_format)
        now = datetime.now()
        # deny requests outside the configured request window
        if now < req_win_open or now > req_win_close:
            return (False, DenyReason.OUSTIDE_REQUEST_WINDOW)

    # deny based on migration configuration and status
    if group_name not in current_app.config["NON_MIGRATION_GROUPS"]:
        mig_cache_group = current_app.config["ASSET_MIGRATION_CACHE"].get(group_name)
        # no requests allowed for completely migrated groups
        if mig_cache_group is None:
            return (False, DenyReason.MIGRATION_COMPLETE)
        # deny request if wallet ID is not in migration group
        if mig_cache_group.get(wallet_id) is None:
            return (False, DenyReason.NOT_IN_MIGRATION_LIST)

    # allow request
    return (True, None)


def _receive_asset_checks(req, cfg):
    # check auth
    auth = req.headers.get("X-Api-Key")
    if auth != cfg["API_KEY"]:
        return {"error": "unauthorized", "code": 401}
    # get request data
    try:
        data = json.loads(req.data)
    except json.JSONDecodeError:
        return {"error": "invalid request data", "code": 400}
    # check wallet_id is valid
    if data and not is_walletid_valid(data.get("wallet_id")):
        return {"error": "invalid wallet ID", "code": 403}
    # parse invoice
    try:
        invoice = rgb_lib.Invoice(data.get("invoice"))
    except (rgb_lib.RgbLibError, TypeError):  # pylint: disable=catching-non-exception
        return {"error": "invalid invoice", "code": 403}

    return {"data": data, "invoice": invoice}
