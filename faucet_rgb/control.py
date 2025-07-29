"""Faucet blueprint to top-up funds."""

import rgb_lib
from flask import Blueprint, current_app, jsonify, request
from rgb_lib import Online, Transfer, TransferStatus, Wallet
from sqlalchemy import select

from faucet_rgb import utils
from faucet_rgb.utils.wallet import amount_from_assignment, get_unspent_list

from .database import Request, db, select_query

bp = Blueprint("control", __name__, url_prefix="/control")


# routes


@bp.route("/assets", methods=["GET"])
def assets():
    """Return the list of RGB assets from rgb-lib."""
    auth = request.headers.get("X-Api-Key")
    if auth != current_app.config["API_KEY_OPERATOR"]:
        return jsonify({"error": "unauthorized"}), 401

    online: Online = current_app.config["ONLINE"]
    wallet: Wallet = current_app.config["WALLET"]
    wallet.refresh(online, None, [], False)
    asset_list = wallet.list_assets([])
    assets_nia = asset_list.nia or []
    assets_cfa = asset_list.cfa or []
    asset_dict = utils.get_asset_dict(assets_nia + assets_cfa)
    return jsonify({"assets": asset_dict})


@bp.route("/delete", methods=["GET"])
def delete_transfers():
    """Delete currently failed transfers."""
    auth = request.headers.get("X-Api-Key")
    if auth != current_app.config["API_KEY_OPERATOR"]:
        return jsonify({"error": "unauthorized"}), 401

    wallet: Wallet = current_app.config["WALLET"]
    res = wallet.delete_transfers(None, False)
    return jsonify({"result": res}), 200


@bp.route("/fail", methods=["GET"])
def fail_transfers():
    """Fail currently pending transfers."""
    auth = request.headers.get("X-Api-Key")
    if auth != current_app.config["API_KEY_OPERATOR"]:
        return jsonify({"error": "unauthorized"}), 401

    online: Online = current_app.config["ONLINE"]
    wallet: Wallet = current_app.config["WALLET"]
    res = wallet.fail_transfers(online, None, False, False)
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

    status_filter, error = _get_status_filter(request.args.get("status"))
    if error:
        return jsonify({"error": error}), 403
    assert status_filter

    online: Online = current_app.config["ONLINE"]
    wallet: Wallet = current_app.config["WALLET"]
    wallet.refresh(online, None, [], False)
    asset_ids = _get_asset_ids(wallet)
    transfers = []
    for asset_id in asset_ids:
        asset_transfers = wallet.list_transfers(asset_id)
        for transfer in asset_transfers:
            if transfer.status not in status_filter:
                continue
            transfers.append(_format_transfer(transfer))
    return jsonify({"transfers": transfers})


@bp.route("/refresh/<asset_id>", methods=["GET"])
def refresh(asset_id: str):
    """Refresh asset transfers."""
    auth = request.headers.get("X-Api-Key")
    if auth != current_app.config["API_KEY_OPERATOR"]:
        return jsonify({"error": "unauthorized"}), 401

    online: Online = current_app.config["ONLINE"]
    wallet: Wallet = current_app.config["WALLET"]
    try:
        res = wallet.refresh(online, asset_id, [], False)
        result = {}
        for k, v in res.items():
            updated_status = None if not v.updated_status else v.updated_status.name
            result[k] = {
                "updated_status": updated_status,
                "failure": v.failure,
            }
        return jsonify({"result": result}), 200
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

    stmt = select_query()
    if asset_group:
        stmt = stmt.where(Request.asset_group == asset_group)
    if asset_id:
        stmt = stmt.where(Request.asset_id == asset_id)
    if recipient_id:
        stmt = stmt.where(Request.recipient_id == recipient_id)
    if status:
        stmt = stmt.where(Request.status == status)
    if wallet_id:
        stmt = stmt.where(Request.wallet_id == wallet_id)

    requests = []
    for req in db.session.scalars(stmt.order_by(Request.idx.desc()).limit(100)):
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

    online: Online = current_app.config["ONLINE"]
    wallet: Wallet = current_app.config["WALLET"]
    unspent_list = get_unspent_list(wallet, online)
    return jsonify({"unspents": unspent_list})


# helpers


def _get_status_filter(status: None | str):
    """
    Return the status filter list based on the query parameter,
    defaulting to pending ones.
    """
    if status is None:
        return [
            TransferStatus.WAITING_COUNTERPARTY,
            TransferStatus.WAITING_CONFIRMATIONS,
        ], None
    if not hasattr(TransferStatus, status.upper()):
        return None, f"unknown status requested: {status}"
    requested_status: TransferStatus = getattr(TransferStatus, status.upper())
    return [requested_status], None


def _get_asset_ids(wallet: Wallet):
    """Return a list of NIA and CFA asset IDs from the wallet."""
    asset_list = wallet.list_assets([])
    assets_nia = asset_list.nia or []
    assets_cfa = asset_list.cfa or []
    return [a.asset_id for a in assets_nia + assets_cfa]


def _format_transfer(transfer: Transfer):
    """Format a transfer object for the API response."""
    ttes = [
        {
            "endpoint": tte.endpoint,
            "transport_type": tte.transport_type.name,
            "used": tte.used,
        }
        for tte in transfer.transport_endpoints
    ]
    for a in transfer.assignments:
        if not a.is_fungible():
            raise RuntimeError("only fungible assignments are supported")
    amounts = [amount_from_assignment(a) for a in transfer.assignments]
    return {
        "status": transfer.status.name,
        "amounts": amounts,
        "kind": transfer.kind.name,
        "txid": transfer.txid,
        "recipient_id": transfer.recipient_id,
        "transfer_transport_endpoints": ttes,
    }
