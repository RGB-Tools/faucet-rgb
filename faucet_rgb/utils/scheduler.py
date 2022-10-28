"""Scheduler utils module."""

from ..scheduler import scheduler


def trigger_task():
    """Trigger execution of donation scheduler task once."""
    scheduler.run_job('batch_donation')
