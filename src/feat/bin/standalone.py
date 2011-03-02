#!/usr/bin/python2.6
import optparse

from twisted.internet import reactor

from feat.agencies.net import standalone
from feat.common import reflect, log, run


# This script is not ment to be run by human hand. It is used by the
# standalone agents to run in seperate process.


class Options(optparse.OptionParser):

    def __init__(self):
        optparse.OptionParser.__init__(self)
        self._setup_options()

    def _setup_options(self):
        self.add_option('-i', '--import', help='import specified module',
                        action='callback', callback=self.load_module,
                        type="str", metavar="MODULE")
        self.add_option('-l', '--log', metavar="FILE",
                        help="file to log to", type="str",
                        default='standalone.log', dest="logfile")

    def load_module(self, option, opt, value, parser):
        reflect.named_module(value)

parser = Options()
options, args = parser.parse_args()

log.FluLogKeeper.init(options.logfile)

run.daemonize(stderr=options.logfile, stdout=options.logfile)
a = standalone.Agency()
a.initiate()
reactor.run()
