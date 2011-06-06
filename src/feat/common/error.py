import re
import StringIO

from twisted.python.failure import Failure

from feat.common import log
from feat.extern.log import log as xlog


class FeatError(Exception):
    """
    An exception that keep information on the cause of its creation.
    The cause may be other exception or a Failure.
    """

    default_error_code = None
    default_error_name = None

    def __init__(self, *args, **kwargs):
        self.data = kwargs.pop('data', None)
        self.cause = kwargs.pop('cause', None)
        default_code = self.default_error_code
        default_name = self.default_error_name or self.__class__.__name__
        self.error_code = kwargs.pop('code', default_code)
        self.error_name = kwargs.pop('name', default_name)

        Exception.__init__(self, *args, **kwargs)

        self.cause_details = None
        self.cause_traceback = None

        if self.cause:
            if isinstance(self.cause, Exception):
                self.cause_details = get_exception_message(self.cause)
            elif isinstance(self.cause, Failure):
                self.causeDetails = get_failure_message(self.cause)
            else:
                self.causeDetails = "Unknown"

            if isinstance(self.cause, Failure):
                f = self.cause
                self.cause = f.value
                try:
                    self.cause_traceback = f.getTraceback()
                except:
                    # Ignore failure.NoCurrentExceptionError
                    pass
            else:
                try:
                    f = Failure()
                    if f.value == self.cause:
                        self.cause_traceback = f.getTraceback()
                except:
                    # Ignore failure.NoCurrentExceptionError
                    pass


def get_exception_message(exception):
    try:
        msg = xlog.getExceptionMessage(exception)
    except IndexError:
        # log.getExceptionMessage do not like exceptions without messages ?
        msg = ""
    if isinstance(exception, FeatError):
        details = exception.cause_details
        if details:
            msg += "; CAUSED BY " + details
    return msg


def get_failure_message(failure):
    try:
        msg = xlog.getFailureMessage(failure)
    except KeyError:
        # Sometime happen for strange error, just when we relly need a message
        msg = failure.getErrorMessage()
    exception = failure.value
    if isinstance(exception, FeatError):
        details = exception.cause_details
        if details:
            msg += "; CAUSED BY " + details
    return msg


def get_exception_traceback(exception=None, cleanup=False):
    #FIXME: Only work if the exception was raised in the current context
    f = Failure(exception)

    if exception and (f.value != exception):
        return "Not Traceback information available"

    io = StringIO.StringIO()
    tb = f.getTraceback()
    if cleanup:
        tb = clean_traceback(tb)
    print >> io, tb
    if isinstance(f.value, FeatError):
        if f.value.causeTraceback:
            print >> io, "\n\nCAUSED BY:\n\n"
            tb = f.value.causeTraceback
            if cleanup:
                tb = clean_traceback(tb)
            print >> io, tb

    return io.getvalue()


def get_failure_traceback(failure, cleanup=False):
    if isinstance(failure.type, str):
        return ""

    io = StringIO.StringIO()
    tb = failure.getTraceback()
    if cleanup:
        tb = clean_traceback(tb)
    print >> io, tb
    exception = failure.value
    if exception and isinstance(exception, FeatError):
        if exception.cause_traceback:
            print >> io, "\n\nCAUSED BY:\n\n"
            tb = exception.cause_traceback
            if cleanup:
                tb = clean_traceback(tb)
            print >> io, tb

    return io.getvalue()


def clean_traceback(tb):
    prefix = __file__[:__file__.find("feat/common/error.py")]
    regex = re.compile("(\s*File\s*\")(%s)([a-zA-Z-_\. \\/]*)(\".*)"
                       % prefix.replace("\\", "\\\\"))

    def cleanup(line):
        m = regex.match(line)
        if m:
            return m.group(1) + ".../" + m.group(3) + m.group(4)
        else:
            return line

    return '\n'.join(map(cleanup, tb.split('\n')))


def handle_failure(logger, failure, template, *args, **kwargs):
    info = kwargs.get("info", None)
    debug = kwargs.get("debug", None)
    msg = get_failure_message(failure)

    if xlog.getCategoryLevel(logger.log_category) in [xlog.LOG, xlog.DEBUG]:
        cleanup = kwargs.get("clean_traceback", False)
        tb = get_failure_traceback(failure, cleanup)
        logger.error(template + ": %s\n%s", *(args + (msg, tb)))
    else:
        logger.error(template + ": %s", *(args + (msg, )))

    if log.verbose:
        if info:
            logger.info("Additional Information:\n%s", info)
        if debug:
            logger.debug("Additional Debug:\n%s", debug)


def handle_exception(logger, exception, template, *args, **kwargs):
    info = kwargs.get("info", None)
    debug = kwargs.get("debug", None)
    msg = get_exception_message(exception)

    if xlog.getCategoryLevel(logger.log_category) in [xlog.LOG, xlog.DEBUG]:
        cleanup = kwargs.get("clean_traceback", False)
        tb = get_exception_traceback(exception, cleanup)
        logger.error(template + ": %s\n%s", *(args + (msg, tb)))
    else:
        logger.error(template + ": %s", *(args + (msg, )))

    if log.verbose:
        if info:
            logger.info("Additional Information:\n%s", debug)
        if debug:
            logger.debug("Additional Debug:\n%s", debug)
