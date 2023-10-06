"""Application exceptions."""


class ConfigurationError(Exception):
    """Configuration error.

    Attributes:
    - errors: list of detected configuration errors
    """

    def __init__(self, errors, message="configuration errors detected"):
        self.errors = errors
        self.message = message
        super().__init__(self.message)
