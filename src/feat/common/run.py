import errno
import sys
import os
import signal
import time

from feat.common import log

PROCESS_TYPE = "feat"


def status(processName, rundir='/tmp', processType=PROCESS_TYPE):
    pid = get_pid(rundir, processType, processName)
    if not pid:
        print "%s %s not running" % (processType, processName)
        return
    if check_pid_running(pid):
        print "%s %s is running with pid %d" % (processType, processName, pid)
    else:
        print "%s %s dead (stale pid %d)" % (processType, processName, pid)
        sys.exit(3)


def stop(processName, rundir='/tmp', processType=PROCESS_TYPE):
    pid = get_pid(rundir, processType, processName)
    if not pid:
        print "%s %s not running" % (processType, processName)
        return
    startClock = time.clock()
    termClock = startClock + 20
    killClock = termClock + 10

    log.debug("run", 'stopping process with pid %d', pid)
    if not term_pid(pid):
        log.warning("run", 'No process with pid %d', pid)
        return  1

    # wait for the kill
    while (check_pid_running(pid)):
        if time.clock() > termClock:
            log.warning("run", "Process with pid %d has not responded "
                        "to TERM for %d seconds, killing", pid, 20)
            kill_pid(pid)
            # so it does not get triggered again
            termClock = killClock + 1.0

        if time.clock() > killClock:
            log.warning("run", "Process with pid %d has not responded to "
                        "KILL for %d seconds, stopping", pid, 10)
            return 1
    print "%s %s with pid %d stopped" % (processType, processName, pid)
    return 0


is_already_daemon = False


def daemonize(stdin='/dev/null', stdout='/dev/null', stderr='/dev/null'):
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

    global is_already_daemon
    if is_already_daemon:
        return

    # first fork
    _fork()
    # do second fork
    _fork()
    # Now I am a daemon!
    # don't add stuff here that can fail, because from now on the program
    # will keep running regardless of tracebacks
    is_already_daemon = True


def acquire_pidfile(rundir, type=PROCESS_TYPE, name=None):
    """
    Open a PID file for writing, using the given process type and
    process name for the filename. The returned file can be then passed
    to writePidFile after forking.

    @rtype:   str
    @returns: file object, open for writing
    """
    _ensure_dir(rundir, "rundir")
    path = _get_pidpath(rundir, type, name)
    return open(path, 'w')


def write_pidfile(rundir, type=PROCESS_TYPE, name=None, file=None):
    """
    Write a pid file in the run directory, using the given process type
    and process name for the filename.

    @rtype:   str
    @returns: full path to the pid file that was written
    """
    # don't shadow builtin file
    pidFile = file
    if pidFile is None:
        _ensure_dir(rundir, "rundir")
        filename = _get_pidpath(rundir, type, name)
        pidFile = open(filename, 'w')
    else:
        filename = pidFile.name
    pidFile.write("%d\n" % (os.getpid(), ))
    pidFile.close()
    os.chmod(filename, 0644)
    return filename


def delete_pidfile(rundir, type=PROCESS_TYPE, name=None, force=False):
    """
    Delete the pid file in the run directory, using the given process type
    and process name for the filename.

    @param force: if errors due to the file not existing should be ignored
    @type  force: bool

    @rtype:   str
    @returns: full path to the pid file that was written
    """
    log.debug(type, 'deleting pid file')
    path = _get_pidpath(rundir, type, name)
    try:
        os.unlink(path)
    except OSError, e:
        if e.errno == errno.ENOENT and force:
            pass
        else:
            raise
    return path


def get_pid(rundir, type=PROCESS_TYPE, name=None):
    """
    Get the pid from the pid file in the run directory, using the given
    process type and process name for the filename.

    @returns: pid of the process, or None if not running or file not found.
    """
    pidPath = _get_pidpath(rundir, type, name)
    log.log('run', 'pidfile for %s %s is %s' % (type, name, pidPath))

    if not os.path.exists(pidPath):
        return

    pidFile = open(pidPath, 'r')
    pid = pidFile.readline()
    pidFile.close()
    if not pid or int(pid) == 0:
        return

    return int(pid)


def signal_pid(pid, signum):
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


def term_pid(pid):
    """
    Send the given process a TERM signal.

    @returns: whether or not the process with the given pid was running
    """
    return signal_pid(pid, signal.SIGTERM)


def kill_pid(pid):
    """
    Send the given process a KILL signal.

    @returns: whether or not the process with the given pid was running
    """
    return signal_pid(pid, signal.SIGKILL)


def check_pid_running(pid):
    """
    Check if the given pid is currently running.

    @returns: whether or not a process with that pid is active.
    """
    return signal_pid(pid, 0)


def wait_pidfile(rundir, type=PROCESS_TYPE, name=None):
    """
    Wait for the given process type and name to have started and created
    a pid file.

    Return the pid.
    """
    # getting it from the start avoids an unneeded time.sleep
    pid = get_pid(rundir, type, name)

    while not pid:
        time.sleep(0.1)
        pid = get_pid(rundir, type, name)

    return pid


def wait_for_term():
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


def _ensure_dir(directory, description):
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


def _get_pidpath(rundir, type, name=None):
    """
    Get the full path to the pid file for the given process type and name.
    """
    path = os.path.join(rundir, '%s.pid' % type)
    if name:
        path = os.path.join(rundir, '%s.%s.pid' % (type, name))
    log.debug('common', 'get_pidpath for type %s, name %r: %s' % (
        type, name, path))
    return path


def _fork():
    try:
        pid = os.fork()
        if pid > 0:
            sys.exit(0)   # exit first parent
    except OSError, e:
        sys.stderr.write("Failed to fork: (%d) %s\n" % (e.errno, e.strerror))
        sys.exit(1)
