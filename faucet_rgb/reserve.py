"""Faucet blueprint to top-up funds."""

from flask import Blueprint, current_app, jsonify, request

bp = Blueprint("reserve", __name__, url_prefix="/reserve")


@bp.route("/top_up_btc", methods=["GET"])
def top_up_btc():
    """Return an address to top-up the faucet's Bitcoin reserve."""
    auth = request.headers.get("X-Api-Key")
    if auth != current_app.config["API_KEY_OPERATOR"]:
        return jsonify({"error": "unauthorized"}), 401
    wallet = current_app.config["WALLET"]
    new_addr = wallet.get_address()
    return jsonify({"address": new_addr})


@bp.route("/top_up_rgb", methods=["GET"])
def top_up_rgb():
    """Return an RGB invoice to top-up the faucet's RGB asset reserve."""
    auth = request.headers.get("X-Api-Key")
    if auth != current_app.config["API_KEY_OPERATOR"]:
        return jsonify({"error": "unauthorized"}), 401
    wallet = current_app.config["WALLET"]
    blind_data = wallet.blind_receive(
        None,
        None,
        None,
        current_app.config["TRANSPORT_ENDPOINTS"],
        current_app.config["MIN_CONFIRMATIONS"],
    )
    return jsonify({"invoice": blind_data.invoice, "expiration": blind_data.expiration_timestamp})
