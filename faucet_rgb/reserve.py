"""Faucet blueprint to top-up funds."""

from flask import Blueprint, current_app, jsonify

bp = Blueprint('reserve', __name__, url_prefix='/reserve')


@bp.route('/top_up', methods=['GET'])
def top_up():
    """Return an address to top-up the faucet's Bitcoin reserve."""
    wallet = current_app.config["WALLET"]
    new_addr = wallet.get_address()
    return jsonify({'address': new_addr})
