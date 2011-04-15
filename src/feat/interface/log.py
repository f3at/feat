from zope.interface import Interface, Attribute

from feat.common import enum

__all__ = ["LogLevel", "ILogKeeper", "ILogger"]


class LogLevel(enum.Enum):
    error, warning, info, debug, log = range(1, 6)


class ILogKeeper(Interface):
    '''Store logging entries'''

    def do_log(level, object, category, format, args,
               depth=1, file_path=None, line_num=None):
        '''Adds a log entry with specified level, category and object.
        @param depth: The depth in the calling stack from the logging call.
        @type  depth: int
        @param file_path: file to show the message as coming from, if caller
                          knows best
        @type  file_path: str
        @param line_num: line to show the message as coming from, if caller
                         knows best
        @type  line_num: int
        '''


class ILogger(Interface):
    '''Can be used to generate contextual logging entries'''

    logname = Attribute("Logging name")

    def log(format, *args):
        pass

    def debug(format, *args):
        pass

    def info(format, *args):
        pass

    def warning(format, *args):
        pass

    def error(format, *args):
        pass

    def logex(level, format, args, depth=1):
        '''Extended logging. Allows changing stack depth.'''
