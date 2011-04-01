import errno
import sys
import os
import optparse

from twisted.internet import reactor

from feat.agencies.net import agency
from feat.common import log


class OptionError(Exception):
    pass


def get_db_connection(agency):
    return agency._database.get_connection(None)


def add_options(parser):
    parser.add_option('-d', '--debug',
                      action="store", type="string", dest="debug",
                      help="Set debug levels.")


def check_options(opts, args):
    return opts, args


class bootstrap(object):

    def __init__(self, parser=None, args=None):
        self._parser = parser
        self.args = args
        self.opts = None
        self.agency = None

    def __enter__(self):
        log.FluLogKeeper.init()
        self._parse_opts()
        self._check_opts()
        if self.opts.debug:
            log.FluLogKeeper.set_debug(self.opts.debug)
        self.agency = self._run_agency()
        return self

    def __exit__(self, type, value, traceback):
        if type is not None:
            if issubclass(type, OptionError):
                print >> sys.stderr, "ERROR: %s" % str(value)
                return True
            return
        reactor.run()

    def _parse_opts(self):
        parser = self._parser or optparse.OptionParser()
        add_options(parser)
        agency.add_options(parser)
        self.opts, self.args = parser.parse_args(args=self.args)

    def _check_opts(self):
        self.opts, self.args = check_options(self.opts, self.args)
        self.opts, self.args = agency.check_options(self.opts, self.args)

    def _run_agency(self):
        a = agency.Agency.from_config(os.environ, self.opts)
        a.initiate()
        return a


def _fork():
    try:
        pid = os.fork()
        if pid > 0:
            sys.exit(0)   # exit first parent
    except OSError, e:
        sys.stderr.write("Failed to fork: (%d) %s\n" % (e.errno, e.strerror))
        sys.exit(1)


def daemonize(stdin='/dev/null', stdout='/dev/null', stderr='/dev/null',
              directory='/'):
    '''
    This forks the current process into a daemon.
    The stdin, stdout, and stderr arguments are file names that
    will be opened and be used to replace the standard file descriptors
    in sys.stdin, sys.stdout, and sys.stderr.
    These arguments are optional and default to /dev/null.

    The fork will switch to the given directory.

    Used by external projects (ft).
    '''
    # Redirect standard file descriptors.
    si = open(stdin, 'r')
    os.dup2(si.fileno(), sys.stdin.fileno())
    try:
        log.FluLogKeeper.redirect_to(stdout, stderr)
    except IOError, e:
        if e.errno == errno.EACCES:
            sys.stderr.write('Permission denied writing to log file %s.' %\
                             e.filename)

    # first fork
    _fork()
    # do second fork
    _fork()
    # Now I am a daemon!
    # don't add stuff here that can fail, because from now on the program
    # will keep running regardless of tracebacks
