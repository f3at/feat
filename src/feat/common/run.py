import errno
import sys
import os
import optparse

from twisted.internet import reactor

from feat.agencies.net import agency
from feat.common import log


class Options(optparse.OptionParser):

    def __init__(self):
        optparse.OptionParser.__init__(self)
        agency.add_options(self)


def get_db_connection(agency):
    return agency._database.get_connection(None)


class bootstrap(object):

    def __enter__(self):
        log.FluLogKeeper.init()
        opts = self.parse_opts()
        self.agency = self.run_agency(opts)
        return self.agency

    def __exit__(self, type, value, traceback):
        reactor.run()

    def parse_opts(self):
        parser = Options()
        (opts, args) = parser.parse_args()
        return opts

    def run_agency(self, opts):
        a = agency.from_config(os.environ, opts)
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
