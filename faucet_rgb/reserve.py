"""Faucet blueprint to top-up funds."""

from flask import Blueprint, current_app, jsonify

bp = Blueprint('reserve', __name__, url_prefix='/reserve')


@bp.route('/top_up_btc', methods=['GET'])
def top_up_btc():
    """Return an address to top-up the faucet's Bitcoin reserve."""
    wallet = current_app.config["WALLET"]
    new_addr = wallet.get_address()
    return jsonify({'address': new_addr})


@bp.route('/top_up_rgb', methods=['GET'])
def top_up_rgb():
    """Return an address to top-up the faucet's Bitcoin reserve."""
    wallet = current_app.config["WALLET"]
    blind_data = wallet.blind(None, None)
    return jsonify({
        'blinded_utxo': blind_data.blinded_utxo,
        'expiration': blind_data.expiration_timestamp
    })
