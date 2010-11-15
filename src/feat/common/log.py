# -*- Mode: Python -*-
# vi:si:et:sw=4:sts=4:ts=4

import sys

from zope.interface import implements

from feat.interface.log import *


class Logger(object):

    implements(ILogger)

    log_name = None
    log_category = "feat"

    def __init__(self, logger):
        self._logger = ILogKeeper(logger)

    ### ILoggable Methods ###

    def log(self, format, *args):
        self._logger.do_log(LogLevel.log, self.log_name,
                            self.log_category, format, args)

    def debug(self, format, *args):
        self._logger.do_log(LogLevel.debug, self.log_name,
                            self.log_category, format, args)

    def info(self, format, *args):
        self._logger.do_log(LogLevel.info, self.log_name,
                            self.log_category, format, args)

    def warning(self, format, *args):
        self._logger.do_log(LogLevel.warning, self.log_name,
                            self.log_category, format, args)

    def error(self, format, *args):
        self._logger.do_log(LogLevel.error, self.log_name,
                            self.log_category, format, args)


class LogProxy(object):
    '''Proxies log entries to another log keeper.'''

    implements(ILogKeeper)

    def __init__(self, logkeeper):
        self._logkeeper = ILogKeeper(logkeeper)

    def do_log(self, level, object, category, format, args,
               depth=1, file_path=None, line_num=None):
        self._logkeeper.do_log(level, object, category, format, args,
               depth=depth+1, file_path=file_path, line_num=line_num)


class FluLogKeeper(object):
    '''Log keeper using flumotion logging library.
    The class method init() should be called before logger instance are used.
    The class method set_debug() is used to set the debug filter string.

    Example::

        > FluLogKeeper.init()
        > FluLogKeeper.set_debug("*:5")
    '''

    implements(ILogKeeper)

    _initialized = False

    @classmethod
    def init(cls, path=None):
        global flulog
        if not cls._initialized:
            from feat.extern.log import log as flulog
            if path:
                sys.stderr = file(path, 'a')
            flulog.init('FEAT_DEBUG')
            flulog.setPackageScrubList('feat', 'twisted')
            flulog.logTwisted()
            cls._initialized = True

    @classmethod
    def set_debug(self, string):
        global flulog
        flulog.setDebug(string)

    ### ILogger Methods ###

    def do_log(self, level, object, category, format, args,
               depth=-1, file_path=None, line_num=None):
        global flulog
        flulog.doLog(int(level), object, category, format, args,
                     where=-depth, filePath=file_path, line=line_num)
