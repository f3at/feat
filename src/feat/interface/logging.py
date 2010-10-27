from zope.interface import Interface, Attribute

from feat.common import enum


class LogLevel(enum.Enum):
    error, warning, info, debug, log = range(1, 6)


class ILogger(Interface):
    '''Store logging entries'''

    def do_log(level, object, category, format, args,
               where=-1, file_path=None, line_num=None):
        '''Adds a log entry with specified level, category and object.
        @param where: what to log file and line number for;
                      -1 for one frame above; -2 and down for higher up.
        @type  where: int
        @param file_path: file to show the message as coming from, if caller
                          knows best
        @type  file_path: str
        @param line_num: line to show the message as coming from, if caller
                         knows best
        @type  line_num: int
        '''


class ILoggable(Interface):
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
