import sys

from twisted.internet import reactor

from feat.common import log
from feat.gateway import gateway

import demo_service

def initialize():
    service.add_document("search", "altavista", "http://www.altavista.com")
    service.add_document("search", "yahoo", "http://www.yahoo.com")
    service.add_document("news", "slashdot", "http://slashdot.org")


service = demo_service.Service()
reactor.callWhenRunning(initialize)

log.FluLogKeeper.init()

models = "demo_models" + ("_" + sys.argv[1] if len(sys.argv) > 1 else "")
__import__(models)

api = gateway.Gateway(service, 7878, "localhost", label="Demo")
reactor.callWhenRunning(api.initiate)

reactor.run()





