"""Faucet blueprint to top-up funds."""

import rgb_lib
from flask import Blueprint, current_app, jsonify, request
from rgb_lib import TransferStatus

from faucet_rgb import utils

from .database import Request

bp = Blueprint("control", __name__, url_prefix="/control")


@bp.route("/assets", methods=["GET"])
def assets():
    """Return the list of RGB assets from rgb-lib."""
    auth = request.headers.get("X-Api-Key")
    if auth != current_app.config["API_KEY_OPERATOR"]:
        return jsonify({"error": "unauthorized"}), 401

    online = current_app.config["ONLINE"]
    wallet = current_app.config["WALLET"]
    wallet.refresh(online, None, [])
    asset_list = wallet.list_assets([])
    asset_dict = utils.get_asset_dict(asset_list.nia + asset_list.cfa)
    return jsonify({"assets": asset_dict})


@bp.route("/delete", methods=["GET"])
def delete_transfers():
    """Delete currently failed transfers."""
    auth = request.headers.get("X-Api-Key")
    if auth != current_app.config["API_KEY_OPERATOR"]:
        return jsonify({"error": "unauthorized"}), 401

    wallet = current_app.config["WALLET"]
    res = wallet.delete_transfers(None, None, False)
    return jsonify({"result": res}), 200


@bp.route("/fail", methods=["GET"])
def fail_transfers():
    """Fail currently pending transfers."""
    auth = request.headers.get("X-Api-Key")
    if auth != current_app.config["API_KEY_OPERATOR"]:
        return jsonify({"error": "unauthorized"}), 401

    online = current_app.config["ONLINE"]
    wallet = current_app.config["WALLET"]
    res = wallet.fail_transfers(online, None, None, False)
    return jsonify({"result": res}), 200


@bp.route("/transfers", methods=["GET"])
def list_transfers():
    """List asset transfers.

    Only transfers with an asset ID are queried, as the asset_id parameter to
    the list_transfers rgb-lib API is mandatory.

    Pending transfers are listed by default. If a valid status is provided via
    query parameter, then transfers in that status are returned instead.
    """
    auth = request.headers.get("X-Api-Key")
    if auth != current_app.config["API_KEY_OPERATOR"]:
        return jsonify({"error": "unauthorized"}), 401

    # set status filter from query parameter or default to pending ones
    status_filter = [
        TransferStatus.WAITING_COUNTERPARTY,
        TransferStatus.WAITING_CONFIRMATIONS,
    ]
    status = request.args.get("status")
    if status is not None:
        if not hasattr(TransferStatus, status.upper()):
            return jsonify({"error": f"unknown status requested: {status}"}), 403
        status_filter = [getattr(TransferStatus, status.upper())]

    # refresh and list transfers in matching status(es)
    online = current_app.config["ONLINE"]
    wallet = current_app.config["WALLET"]
    wallet.refresh(online, None, [])
    asset_list = wallet.list_assets([])
    asset_ids = [a.asset_id for a in asset_list.nia + asset_list.cfa]
    transfers = []
    for asset_id in asset_ids:
        asset_transfers = wallet.list_transfers(asset_id)
        for transfer in asset_transfers:
            if transfer.status not in status_filter:
                continue
            ttes = [
                {
                    "endpoint": tte.endpoint,
                    "transport_type": tte.transport_type.name,
                    "used": tte.used,
                }
                for tte in transfer.transport_endpoints
            ]
            transfers.append(
                {
                    "status": transfer.status.name,
                    "amount": transfer.amount,
                    "kind": transfer.kind.name,
                    "txid": transfer.txid,
                    "recipient_id": transfer.recipient_id,
                    "transfer_transport_endpoints": ttes,
                }
            )
    return jsonify({"transfers": transfers})


@bp.route("/refresh/<asset_id>", methods=["GET"])
def refresh(asset_id):
    """Refresh asset transfers."""
    auth = request.headers.get("X-Api-Key")
    if auth != current_app.config["API_KEY_OPERATOR"]:
        return jsonify({"error": "unauthorized"}), 401

    online = current_app.config["ONLINE"]
    wallet = current_app.config["WALLET"]
    try:
        res = wallet.refresh(online, asset_id, [])
        return jsonify({"result": res}), 200
    except rgb_lib.RgbLibError.AssetNotFound:
        return jsonify({"error": f"unknown asset ID: {asset_id}"}), 404
    except Exception as err:  # pylint: disable=broad-except
        return jsonify({"error": f"unknown error: {err}"}), 500


@bp.route("/requests", methods=["GET"])
def list_requests():
    """Return requests.

    Max 100 requests are returned.
    Request can include filters as query parameters:
    - 'status'
    - 'asset_group'
    - 'asset_id'
    - 'recipient_id'
    - 'wallet_id'

    If no filter is provided, all requests in status 20 are returned
    """
    auth = request.headers.get("X-Api-Key")
    if auth != current_app.config["API_KEY_OPERATOR"]:
        return jsonify({"error": "unauthorized"}), 401

    asset_group = request.args.get("asset_group")
    asset_id = request.args.get("asset_id")
    recipient_id = request.args.get("recipient_id")
    status = request.args.get("status")
    wallet_id = request.args.get("wallet_id")
    if all(a is None for a in [asset_group, asset_id, recipient_id, status, wallet_id]):
        status = 20

    reqs = Request.query
    if asset_group:
        reqs = reqs.filter_by(asset_group=asset_group)
    if asset_id:
        reqs = reqs.filter_by(asset_id=asset_id)
    if recipient_id:
        reqs = reqs.filter_by(recipient_id=recipient_id)
    if status:
        reqs = reqs.filter_by(status=status)
    if wallet_id:
        reqs = reqs.filter_by(wallet_id=wallet_id)

    requests = []
    for req in reqs.order_by(Request.idx.desc()).slice(0, 100).all():
        requests.append(
            {
                "idx": req.idx,
                "timestamp": req.timestamp,
                "status": req.status,
                "wallet_id": req.wallet_id,
                "recipient_id": req.recipient_id,
                "invoice": req.invoice,
                "asset_group": req.asset_group,
                "asset_id": req.asset_id,
                "amount": req.amount,
            }
        )

    return jsonify({"requests": requests})


@bp.route("/unspents", methods=["GET"])
def unspents():
    """Return the list of wallet unspents."""
    auth = request.headers.get("X-Api-Key")
    if auth != current_app.config["API_KEY_OPERATOR"]:
        return jsonify({"error": "unauthorized"}), 401

    online = current_app.config["ONLINE"]
    wallet = current_app.config["WALLET"]
    unspent_list = utils.wallet.get_unspent_list(wallet, online)
    return jsonify({"unspents": unspent_list})
