# -*- Mode: Python -*-
# vi:si:et:sw=4:sts=4:ts=4


from zope.interface import implements

from feat.interface.logging import ILogger, ILoggable, LogLevel


class Loggable(object):

    implements(ILoggable)

    log_name = None
    log_category = None

    def __init__(self, logger):
        self._logger = ILogger(logger)

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


class FluLogger(object):
    '''Logger using flumotion logging library.
    The class method init() should be called before logger instance are used.
    The class method set_debug() is used to set the debug filter string.

    Example::

        > FluLogger.init()
        > FluLogger.set_debug("*:5")
    '''

    implements(ILogger)

    @classmethod
    def init(cls):
        global flulog
        from feat.extern.log import log as flulog
        flulog.init('FEAT_DEBUG')
        flulog.setPackageScrubList('feat', 'twisted')

    @classmethod
    def set_debug(self, string):
        global flulog
        flulog.setDebug(string)

    ### ILogger Methods ###

    def do_log(self, level, object, category, format, args,
               where=-1, file_path=None, line_num=None):
        global flulog
        flulog.doLog(int(level), object, category, format, args,
                     where=where, filePath=file_path, line=line_num)
