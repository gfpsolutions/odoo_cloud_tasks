class ToolkitError(Exception):
    """An error whose message is meant to be shown to the user as-is."""


class ConfigError(ToolkitError):
    pass


class SafetyError(ToolkitError):
    pass


class OdooError(ToolkitError):
    def __init__(self, message, status=None, name=None):
        super().__init__(message)
        self.status = status
        self.name = name
