from zope.interface import Interface

from feat.common import enum


class LogLevel(enum.Enum):
    log, debug, info, warning, error = range(5)


class ILogger(Interface):

    def log_entry(level, category, name, format, *args, **kwargs):
        pass


class ILoggable(Interface):

    def log(format, *args, **kwargs):
        pass

    def debug(format, *args, **kwargs):
        pass

    def info(format, *args, **kwargs):
        pass

    def warning(format, *args, **kwargs):
        pass

    def error(format, *args, **kwargs):
        pass
