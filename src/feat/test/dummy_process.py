#!/usr/bin/python
import sys
import os
import optparse
import signal

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from feat.common import run, log


class CustomException(Exception):
    pass


def _create_parser():
    parser = optparse.OptionParser()
    parser.add_option('--fail', action="store_true", dest="fail",
                      help="throw exception")
    parser.add_option('--daemonize', action="store_true", dest="daemonize",
                      help="should deamonize")
    return parser


def sigusr1_handler(_signum, _frame):
    sys.exit(0)


if __name__ == '__main__':
    log.init()
    parser = _create_parser()
    opt, args = parser.parse_args()
    if opt.fail:
        raise CustomException("I'm failing as you have asked.")
    if opt.daemonize:
        logfile = "dummy.log"
        run.daemonize(stdout=logfile, stderr=logfile)

    signal.signal(signal.SIGUSR1, sigusr1_handler)

    rundir = os.path.curdir
    pid_file = run.acquire_pidfile(rundir, "dummy_process")
    path = run.write_pidfile(rundir, file=pid_file)
    print "Written pid file to %s" % (path, )

    try:
        while True:
            pass
    except KeyboardInterrupt:
        pass
