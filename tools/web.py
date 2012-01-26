#!/usr/bin/python
from twisted.internet import reactor

from flt.agents.hapi import dummy, web
from feat.common import log


log.init()

agent = dummy.DummyAgent()
port = 8800
server = web.ServerWrapper(agent, port)
server.start()

print "Listening on http://127.0.0.1:%d" % port

reactor.run()
