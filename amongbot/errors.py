class AmongBotException(Exception):
    """Base class for exceptions in amongbot"""
    pass


class SameValueError(AmongBotException):
    def __init__(self, value=None):
        self.value = value

    def __str__(self):
        return self.value
