import errno
import sys
import os
import optparse
import signal
import time

from twisted.internet import reactor

from feat.agencies.net import agency
from feat.common import log

PROCESS_TYPE = 'feat'
SERVICE_NAME = 'host'
LOGDIR = '/var/log/feat'
RUNDIR = '/var/log/feat'


class OptionError(Exception):
    pass


def get_db_connection(agency):
    return agency._database.get_connection()


def add_options(parser):
    parser.add_option('-d', '--debug',
                      action="store", type="string", dest="debug",
                      help="Set debug levels.")

    # Service options

    group = optparse.OptionGroup(parser, "Service options")

    group.add_option('-s', '--service-name',
                     action="store", type="string", dest="serviceName",
                     help="name to use for flog and pid files "
                          "when run as a daemon",
                     default=SERVICE_NAME)
    group.add_option('-D', '--daemonize',
                     action="store_true", dest="daemonize",
                     default=False,
                     help="run in background as a daemon")
    group.add_option('', '--daemonize-to',
                     action="store", dest="daemonizeTo",
                     help="what directory to run from when daemonizing",
                     default='/')
    group.add_option('-L', '--logdir',
                      action="store", dest="logdir",
                      help=("agent log directory (default: %s)" % LOGDIR),
                      default=LOGDIR)
    group.add_option('-R', '--rundir',
                      action="store", dest="rundir",
                      help=("agent run directory (default: %s)" % RUNDIR),
                      default=RUNDIR)

    parser.add_option_group(group)


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
        startup(PROCESS_TYPE, self.opts.serviceName, self.opts.daemonize,
                self.opts.daemonizeTo, self.opts.logdir, self.opts.rundir)
        reactor.run()

    def _parse_opts(self):
        parser = self._parser or optparse.OptionParser()
        add_options(parser)
        agency.add_options(parser)
        self.opts, self.args = parser.parse_args(args=self.args)
        self.opts.agency_journal = os.path.join(self.opts.logdir,
                                                self.opts.agency_journal)

    def _check_opts(self):
        if self.opts.daemonizeTo and not self.opts.daemonize:
            sys.stderr.write(
                'ERROR: --daemonize-to can only be '
                'used with -D/--daemonize.\n')
            return 1

        if self.opts.serviceName and not self.opts.daemonize:
            sys.stderr.write(
                'ERROR: --service-name can only be '
                'used with -D/--daemonize.\n')
            return 1
        self.opts, self.args = check_options(self.opts, self.args)
        self.opts, self.args = agency.check_options(self.opts, self.args)

    def _run_agency(self):
        a = agency.Agency.from_config(os.environ, self.opts)
        return a


def status(processName, rundir='/tmp', processType=PROCESS_TYPE):
    pid = getPid(rundir, processType, processName)
    if not pid:
        print "%s %s not running" % (processType, processName)
        sys.exit(3)
    if checkPidRunning(pid):
        print "%s %s is running with pid %d" % (processType, processName, pid)
    else:
        print "%s %s dead (stale pid %d)" % (processType, processName, pid)
        sys.exit(3)


def stop(processName, rundir='/tmp', processType=PROCESS_TYPE):
    pid = getPid(rundir, processType, processName)
    if not pid:
        print "%s %s not running" % (processType, processName)
        return
    startClock = time.clock()
    termClock = startClock + 20
    killClock = termClock + 10

    log.debug('stopping process with pid %d', pid)
    if not termPid(pid):
        log.warning('No process with pid %d', pid)
        return  1

    # wait for the kill
    while (checkPidRunning(pid)):
        if time.clock() > termClock:
            log.warning("Process with pid %d has not responded to TERM " \
                "for %d seconds, killing", pid, 20)
            killPid(pid)
            # so it does not get triggered again
            termClock = killClock + 1.0

        if time.clock() > killClock:
            log.warning("Process with pid %d has not responded to KILL " \
                "for %d seconds, stopping", pid, 10)
            return 1
    print "%s %s with pid %d stopped" % (processType, processName, pid)
    return 0


def startup(processType, processName, daemonize=False,
            daemonizeTo='/', logdir='/tmp', rundir='/tmp'):
    """
    Prepare a process for starting, logging appropriate standarised messages.
    First daemonizes the process, if daemonize is true.

    @param processType: The process type, for example 'worker'. Used
                        as the first part of the log file and PID file names.
    @type  processType: str
    @param processName: The service name of the process. Used to
                        disambiguate different instances of the same daemon.
                        Used as the second part of log file and PID file names.
    @type  processName: str
    @param daemonize:   whether to daemonize the current process.
    @type  daemonize:   bool
    @param daemonizeTo: The directory that the daemon should run in.
    @type  daemonizeTo: str
    """
    pid = getPid(rundir, processType, processName)
    if pid:
        if checkPidRunning(pid):
            log.error(processType,
                "%s is running with pid %d" % (processName, pid))
            sys.exit(1)

    log.info(processType, "Starting %s '%s'", processType, processName)

    if daemonize:
        _daemonizeHelper(processType, daemonizeTo, processName, logdir, rundir)

    log.info(processType, "Started %s '%s'", processType, processName)

    def shutdownStarted():
        log.info(processType, "Stopping %s '%s'", processType, processName)

    def shutdownEnded():
        log.info(processType, "Stopped %s '%s'", processType, processName)

    # import inside function so we avoid affecting startup
    from twisted.internet import reactor
    reactor.addSystemEventTrigger('before', 'shutdown',
                                  shutdownStarted)
    reactor.addSystemEventTrigger('after', 'shutdown',
                                  shutdownEnded)


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


def ensureDir(directory, description):
    """
    Ensure the given directory exists, creating it if not.

    @raise errors.FatalError: if the directory could not be created.
    """
    if not os.path.exists(directory):
        try:
            os.makedirs(directory)
        except OSError, e:
            sys.stderr.write("could not create %s directory %s: %s" % (
                             description, directory, str(e)))


def _daemonizeHelper(processType, daemonizeTo='/', processName=None,
                     logdir='/tmp', rundir='/tmp'):
    """
    Daemonize a process, writing log files and PID files to conventional
    locations.

    @param processType: The process type, for example 'worker'. Used
                        as the first part of the log file and PID file names.
    @type  processType: str
    @param daemonizeTo: The directory that the daemon should run in.
    @type  daemonizeTo: str
    @param processName: The service name of the process. Used to
                        disambiguate different instances of the same daemon.
                        Used as the second part of log file and PID file names.
    @type  processName: str
    """

    ensureDir(logdir, "log dir")
    ensureDir(rundir, "run dir")

    pid = getPid(processType, processName)
    if pid:
        raise SystemError(
            "A %s service%s is already running with pid %d" % (
                processType, processName and ' named %s' % processName or '',
                pid))

    log.debug(processType, "%s service named '%s' daemonizing",
        processType, processName)

    if processName:
        logPath = os.path.join(logdir, '%s.%s.log' %
                               (processType, processName))
    else:
        logPath = os.path.join(logdir, '%s.log' % (processType, ))
    log.debug(processType, 'Further logging will be done to %s', logPath)

    pidFile = _acquirePidFile(rundir, processType, processName)

    # here we daemonize; so we also change our pid
    daemonize(stdout=logPath, stderr=logPath, directory=daemonizeTo)

    log.debug(processType, 'Started daemon')

    # from now on I should keep running until killed, whatever happens
    path = writePidFile(rundir, processType, processName, file=pidFile)
    log.debug(processType, 'written pid file %s', path)

    # import inside function so we avoid affecting startup
    from twisted.internet import reactor

    def _deletePidFile():
        log.debug(processType, 'deleting pid file')
        deletePidFile(rundir, processType, processName)
    reactor.addSystemEventTrigger('after', 'shutdown',
                                  _deletePidFile)


def _getPidPath(rundir, type, name=None):
    """
    Get the full path to the pid file for the given process type and name.
    """
    path = os.path.join(rundir, '%s.pid' % type)
    if name:
        path = os.path.join(rundir, '%s.%s.pid' % (type, name))
    log.debug('common', 'getPidPath for type %s, name %r: %s' % (
        type, name, path))
    return path


def writePidFile(rundir, type, name=None, file=None):
    """
    Write a pid file in the run directory, using the given process type
    and process name for the filename.

    @rtype:   str
    @returns: full path to the pid file that was written
    """
    # don't shadow builtin file
    pidFile = file
    if pidFile is None:
        ensureDir(rundir, "rundir")
        filename = _getPidPath(rundir, type, name)
        pidFile = open(filename, 'w')
    else:
        filename = pidFile.name
    pidFile.write("%d\n" % (os.getpid(), ))
    pidFile.close()
    os.chmod(filename, 0644)
    return filename


def _acquirePidFile(rundir, type, name=None):
    """
    Open a PID file for writing, using the given process type and
    process name for the filename. The returned file can be then passed
    to writePidFile after forking.

    @rtype:   str
    @returns: file object, open for writing
    """
    ensureDir(rundir, "rundir")
    path = _getPidPath(rundir, type, name)
    return open(path, 'w')


def deletePidFile(rundir, type, name=None, force=False):
    """
    Delete the pid file in the run directory, using the given process type
    and process name for the filename.

    @param force: if errors due to the file not existing should be ignored
    @type  force: bool

    @rtype:   str
    @returns: full path to the pid file that was written
    """
    path = _getPidPath(rundir, type, name)
    try:
        os.unlink(path)
    except OSError, e:
        if e.errno == errno.ENOENT and force:
            pass
        else:
            raise
    return path


def getPid(rundir, type, name=None):
    """
    Get the pid from the pid file in the run directory, using the given
    process type and process name for the filename.

    @returns: pid of the process, or None if not running or file not found.
    """

    pidPath = _getPidPath(rundir, type, name)
    log.log('common', 'pidfile for %s %s is %s' % (type, name, pidPath))
    if not os.path.exists(pidPath):
        return

    pidFile = open(pidPath, 'r')
    pid = pidFile.readline()
    pidFile.close()
    if not pid or int(pid) == 0:
        return

    return int(pid)


def signalPid(pid, signum):
    """
    Send the given process a signal.

    @returns: whether or not the process with the given pid was running
    """
    try:
        os.kill(pid, signum)
        return True
    except OSError, e:
        # see man 2 kill
        if e.errno == errno.EPERM:
            # exists but belongs to a different user
            return True
        if e.errno == errno.ESRCH:
            # pid does not exist
            return False
        raise


def termPid(pid):
    """
    Send the given process a TERM signal.

    @returns: whether or not the process with the given pid was running
    """
    return signalPid(pid, signal.SIGTERM)


def killPid(pid):
    """
    Send the given process a KILL signal.

    @returns: whether or not the process with the given pid was running
    """
    return signalPid(pid, signal.SIGKILL)


def checkPidRunning(pid):
    """
    Check if the given pid is currently running.

    @returns: whether or not a process with that pid is active.
    """
    return signalPid(pid, 0)


def waitPidFile(rundir, type, name=None):
    """
    Wait for the given process type and name to have started and created
    a pid file.

    Return the pid.
    """
    # getting it from the start avoids an unneeded time.sleep
    pid = getPid(rundir, type, name)

    while not pid:
        time.sleep(0.1)
        pid = getPid(rundir, type, name)

    return pid


def waitForTerm():
    """
    Wait until we get killed by a TERM signal (from someone else).
    """

    class Waiter:

        def __init__(self):
            self.sleeping = True
            import signal
            self.oldhandler = signal.signal(signal.SIGTERM,
                                            self._SIGTERMHandler)

        def _SIGTERMHandler(self, number, frame):
            self.sleeping = False

        def sleep(self):
            while self.sleeping:
                time.sleep(0.1)

    waiter = Waiter()
    waiter.sleep()
