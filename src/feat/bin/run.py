#!/usr/bin/python2.6
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

parser = Options()
(opts, args) = parser.parse_args()

log.FluLogKeeper.init()

a = agency.Agency(msg_host=opts.msg_host, msg_port=opts.msg_port,
                  msg_user=opts.msg_user, msg_password=opts.msg_password,
                  db_host=opts.db_host, db_port=opts.db_port,
                  db_name=opts.db_name)
reactor.run()
