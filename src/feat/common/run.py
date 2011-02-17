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
        self._setup_options()

    def _setup_options(self):
        # messaging related options
        self.add_option('-m', '--msghost', dest="msg_host",
                        help="host of messaging server to connect to",
                        metavar="HOST", default="localhost")
        self.add_option('-p', '--msgport', dest="msg_port",
                        help="port of messaging server to connect to",
                        metavar="PORT", default=5672, type="int")
        self.add_option('-u', '--msguser', dest="msg_user",
                        help="username to loging to messaging server",
                        metavar="USER", default="guest")
        self.add_option('-c', '--msgpass', dest="msg_password",
                        help="password to messaging server",
                        metavar="PASSWORD", default="guest")

        # database related options
        self.add_option('-D', '--dbhost', dest="db_host",
                        help="host of database server to connect to",
                        metavar="HOST", default="localhost")
        self.add_option('-P', '--dbport', dest="db_port",
                        help="port of messaging server to connect to",
                        metavar="PORT", default=5984, type="int")
        self.add_option('-N', '--dbname', dest="db_name",
                        help="host of database server to connect to",
                        metavar="NAME", default="feat")

        # manhole specific
        self.add_option('-k', '--pubkey', dest='pub_key',
                        help="public key used by the manhole",
                        default='public.key')
        self.add_option('-K', '--privkey', dest='priv_key',
                        help="private key used by the manhole",
                        default='private.key')
        self.add_option('-A', '--authorized', dest='authorized_keys',
                        help="file with authorized keys to be used by manhole",
                        default="authorized_keys")
        self.add_option('-M', '--manhole', type="int", dest='manhole_port',
                        help="port for the manhole to listen", metavar="PORT")


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
        a = agency.Agency(
            msg_host=opts.msg_host, msg_port=opts.msg_port,
            msg_user=opts.msg_user, msg_password=opts.msg_password,
            db_host=opts.db_host, db_port=opts.db_port,
            db_name=opts.db_name,
            public_key=opts.pub_key, private_key=opts.priv_key,
            authorized_keys=opts.authorized_keys,
            manhole_port=opts.manhole_port)
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
