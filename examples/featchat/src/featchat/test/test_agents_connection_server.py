# F3AT - Flumotion Asynchronous Autonomous Agent Toolkit
# Copyright (C) 2010,2011 Flumotion Services, S.A.
# All rights reserved.

# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License along
# with this program; if not, write to the Free Software Foundation, Inc.,
# 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA.

# See "LICENSE.GPL" in the source distribution for more information.

# Headers in this file shall remain intact.

from zope.interface import implements
from twisted.protocols import basic
from twisted.internet import reactor, protocol

from feat.common import defer, log
from feat.test import common
from featchat.agents.connection import server


class DummyAgent(common.Mock, log.LogProxy):
    implements(server.IConnectionAgent)

    def __init__(self, logkeeper):
        log.LogProxy.__init__(self, logkeeper)
        common.Mock.__init__(self)
        self.valid = True

    @common.Mock.record
    def validate_session(self, session_id):
        return self.valid

    @common.Mock.record
    def publish_message(self, body):
        pass

    @common.Mock.stub
    def connection_lost(self, session_id):
        pass


class ClientProt(basic.LineReceiver):

    def __init__(self):
        self.lines = list()

    def lineReceived(self, line):
        self.lines.append(line)


def connect(port, host='127.0.0.1'):

    prot = ClientProt()

    def give():
        return prot

    factory = protocol.ClientFactory()
    factory.protocol = give
    reactor.connectTCP(host, port, factory)
    return prot


@common.attr(timescale=0.1)
class ServerTest(common.TestCase):

    def setUp(self):
        common.TestCase.setUp(self)
        self.agent = DummyAgent(self)
        self.server = server.ChatServer(self.agent, port=0,
                                        client_disconnect_timeout=1)
        self.server.start()

    @defer.inlineCallbacks
    def testListensAndDisconnectsAfterTimeout(self):
        self.assertFalse(self.server.port is None)
        connect(self.server.port)
        yield self.wait_for(self._clients(1), 1)
        # we don't send session, we should get disconnected
        yield self.wait_for(self._clients(0), 2)

    @defer.inlineCallbacks
    def testAuthenticate(self):
        # first test client sending garbage
        prot = connect(self.server.port)
        yield self.wait_for(self._clients(1), 1)
        prot.sendLine('confusing stuff')
        yield common.delay(None, 0.01)
        self.assertTrue(self._clients(0)())

        # client publishing msg without authorization
        prot = connect(self.server.port)
        yield self.wait_for(self._clients(1), 1)
        prot.sendLine('msg stuff')
        yield common.delay(None, 0.01)
        self.assertTrue(self._clients(0)())

        # now test positive path
        prot = connect(self.server.port)
        yield self.wait_for(self._clients(1), 1)
        prot.sendLine('session_id stuff')
        yield common.delay(None, 0.01)
        self.assertCalled(self.agent, 'validate_session')
        self.assertTrue(self._clients(1)())
        prot.transport.loseConnection()
        yield self.wait_for(self._clients(0), 1)

        # negative path
        prot = connect(self.server.port)
        yield self.wait_for(self._clients(1), 1)
        self.agent.valid = False
        prot.sendLine('session_id stuff')
        yield common.delay(None, 0.01)
        self.assertCalled(self.agent, 'validate_session', times=2)
        self.assertTrue(self._clients(0)())

    @defer.inlineCallbacks
    def testSendingAndReceivingMsg(self):
        # connect 2 authorized clients and one pending,
        # after a client sends a message, it should be dispatched to the
        # authorized protocols and to the agent
        n = 3
        prots = [connect(self.server.port) for x in range(n)]
        yield self.wait_for(self._clients(n), 1)

        [prot.sendLine('session_id stuff_%d' % (i, ))
         for prot, i in zip(prots[0:-1], range(n-1))]
        yield common.delay(None, 0.01)
        self.assertCalled(self.agent, 'validate_session', times=n-1)
        self.assertTrue(self._clients(n)())

        # get the list of connected clients and do validate it
        clients = self.server.get_list()
        self.assertEqual(2, len(clients))
        for ses_id, ip in clients.items():
            self.assertEqual('127.0.0.1', ip)
            self.failUnlessSubstring('stuff_', ses_id)

        prots[0].sendLine('msg some nice message')
        yield common.delay(None, 0.01)
        for prot in prots[0:-1]:
            self.assertEqual(['msg some nice message'], prot.lines)
            del(prot.lines[:])
        self.assertEqual([], prots[-1].lines)
        self.assertCalled(self.agent, 'publish_message')

        # now check that message comming from the agent
        # gets dispatched the same way
        self.server.broadcast('message from the agent')
        yield common.delay(None, 0.01)
        for prot in prots[0:-1]:
            self.assertEqual(['msg message from the agent'], prot.lines)
            del(prot.lines[:])
        self.assertEqual([], prots[-1].lines)
        self.assertCalled(self.agent, 'publish_message')

        # test that after stopping the server the agent is  notified correctly
        self.server.stop()
        yield common.delay(None, 0.01)
        self.assertCalled(self.agent, 'connection_lost', times=2)

    def tearDown(self):
        self.server.stop()

    def _clients(self, num):

        def check():
            return len(self.server._connections) == num

        return check
