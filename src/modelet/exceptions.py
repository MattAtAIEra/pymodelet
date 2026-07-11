class ModelException(Exception):
    """Raised when Modelet fails to build or execute a SQL statement."""

    def __init__(self, message, cause=None):
        super().__init__(message)
        self.cause = cause
