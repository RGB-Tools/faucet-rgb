"""Default application settings."""

import logging


class Config():  # pylint: disable=too-few-public-methods
    """Create and configure the app."""
    SECRET_KEY = 'defaultsecretkey'
    API_KEY = 'defaultapikey'
    API_KEY_OPERATOR = 'defaultoperatorapikey'
    BEHIND_PROXY = False
    ELECTRUM_URL = 'ssl://electrum.rgbtools.org:50012'
    PROXY_URL = 'http://proxy.rgbtools.org'
    DATABASE_NAME = 'db.sqlite3'
    LOG_FILENAME = 'main.log'
    LOG_FILENAME_SCHED = 'scheduler.log'
    LOG_LEVEL_CONSOLE = 'INFO'
    LOG_LEVEL_FILE = 'DEBUG'
    DATA_DIR = 'data'
    NETWORK = 'testnet'
    XPUB = None
    MNEMONIC = None
    NAME = None
    ASSETS = {}
    MIN_REQUESTS = 10
    MAX_WAIT_MINUTES = 10
    SCHEDULER_INTERVAL = 60
    SINGLE_ASSET_SEND = True


class SchedulerFilter(logging.Filter):  # pylint: disable=too-few-public-methods
    """Filter out apscheduler logs."""

    def filter(self, record):
        if record.name.startswith('apscheduler'):
            return False
        return True


LOG_TIMEFMT = '%Y-%m-%d %H:%M:%S %z'
LOG_TIMEFMT_SIMPLE = '%d %b %H:%M:%S'
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'verbose': {
            'format':
            '[%(asctime)s] %(levelname).3s [%(name)s:%(lineno)s] %(threadName)s : %(message)s',
            'datefmt': LOG_TIMEFMT,
        },
        'simple': {
            'format': '%(asctime)s %(levelname).3s: %(message)s',
            'datefmt': LOG_TIMEFMT_SIMPLE,
        },
    },
    'handlers': {
        'console': {
            'level': Config.LOG_LEVEL_CONSOLE,
            'class': 'logging.StreamHandler',
            'formatter': 'simple',
            'stream': 'ext://sys.stdout',
            'filters': ['no_sched'],
        },
        'file': {
            'level': Config.LOG_LEVEL_FILE,
            'class': 'logging.handlers.RotatingFileHandler',
            'filename': Config.LOG_FILENAME,
            'maxBytes': 1048576,
            'backupCount': 7,
            'formatter': 'verbose',
            'filters': ['no_sched'],
        },
        'file_sched': {
            'level': 'INFO',
            'class': 'logging.handlers.RotatingFileHandler',
            'filename': Config.LOG_FILENAME_SCHED,
            'maxBytes': 1048576,
            'backupCount': 7,
            'formatter': 'verbose',
        },
    },
    'filters': {
        'no_sched': {
            '()': SchedulerFilter,
        },
    },
    'loggers': {
        '': {
            'handlers': ['console', 'file'],
            'level': 'DEBUG',
        },
        'apscheduler': {
            'handlers': ['file_sched'],
            'level': 'DEBUG',
        },
    },
}
