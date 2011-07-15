# -*- Mode: Python -*-
# vi:si:et:sw=4:sts=4:ts=4

import os
import sys

from zope.interface import implements

from feat.interface.log import *


verbose = os.environ.get("FEAT_VERBOSE", "NO").upper() in ("YES", "1", "TRUE")


def set_default(keeper):
    global _default_keeper
    _default_keeper = keeper


def get_default():
    global _default_keeper
    return _default_keeper


def create_logger(category="feat"):
    global _default_keeper
    return Logger(_default_keeper, log_category=category)


def logex(category, level, format, args=(), depth=1, log_name=None,
          file_path=None, line_num=None):
    global _default_keeper
    _default_keeper.do_log(level, log_name, category,
                           format, args, depth=depth,
                           file_path=file_path, line_num=line_num)


def log(category, format, *args):
    global _default_keeper
    _default_keeper.do_log(LogLevel.log, None, category, format, args)


def debug(category, format, *args):
    global _default_keeper
    _default_keeper.do_log(LogLevel.debug, None, category, format, args)


def info(category, format, *args):
    global _default_keeper
    _default_keeper.do_log(LogLevel.info, None, category, format, args)


def warning(category, format, *args):
    global _default_keeper
    _default_keeper.do_log(LogLevel.warning, None, category, format, args)


def error(category, format, *args):
    global _default_keeper
    _default_keeper.do_log(LogLevel.error, None, category, format, args)


class Logger(object):

    implements(ILogger)

    log_name = None
    log_category = "feat"

    def __init__(self, log_keeper, log_category=None):
        if log_keeper:
            self._logger = ILogKeeper(log_keeper)
        else:
            self._logger = VoidLogKeeper()

        if log_category is not None:
            self.log_category = log_category

    ### ILoggable Methods ###

    def logex(self, level, format, args, depth=1,
              file_path=None, line_num=None):
        self._logger.do_log(level, self.log_name,
                            self.log_category, format, args, depth=depth+1,
                            file_path=file_path, line_num=line_num)

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


class VoidLogKeeper(object):

    implements(ILogKeeper)

    def do_log(self, *args):
        pass


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
            if path:
                sys.stderr = file(path, 'a')
            from feat.extern.log import log as flulog
            flulog.init('FEAT_DEBUG')
            flulog.setPackageScrubList('feat', 'twisted')
            flulog.logTwisted()
            if get_default() is None:
                set_default(cls())
            cls._initialized = True

    @classmethod
    def redirect_to(cls, stdout, stderr):
        global flulog
        flulog.outputToFiles(stdout, stderr)

    @classmethod
    def set_debug(self, string):
        global flulog
        flulog.setDebug(string)

    @classmethod
    def get_debug(self):
        global flulog
        return flulog.getDebug()

    ### ILogger Methods ###

    def do_log(self, level, object, category, format, args,
               depth=-1, file_path=None, line_num=None):
        global flulog
        flulog.doLog(int(level), object, category, format, args,
                     where=depth, filePath=file_path, line=line_num)


_default_keeper = None
