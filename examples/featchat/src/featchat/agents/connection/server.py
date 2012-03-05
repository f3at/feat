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

from zope.interface import implements, classProvides
from twisted.internet import reactor, protocol
from twisted.protocols import basic

from feat.common import serialization, defer, time, log
from feat.agents.base import replay

from featchat.application import featchat

from featchat.agents.connection.interface import (IChatServer,
                                                  IChatServerFactory,
                                                  IConnectionAgent)

@featchat.register_restorator
class DummyServer(serialization.Serializable):
    classProvides(IChatServerFactory)
    implements(IChatServer)

    def __init__(self, agent, port, client_disconnect_timeout=10):
        self._agent = IConnectionAgent(agent)
        self.port = port
        self._messages = list()

    ### IChatServer ###

    @replay.side_effect
    def start(self):
        pass

    @replay.side_effect
    def stop(self):
        pass

    @replay.side_effect
    def get_list(self):
        return dict()

    @replay.side_effect
    def broadcast(self, body):
        self._messages.append(body)

    ### methods usufull for testing ###

    def publish_message(self, body):
        self._agent.publish_message(body)

    def get_messages(self):
        return self._messages

    ### python specific ###

    def __eq__(self, other):
        if type(self) != type(other):
            return NotImplemented
        return self.port == other.port

    def __ne__(self, other):
        if type(self) != type(other):
            return NotImplemented
        return not self.__eq__(other)


@featchat.register_restorator
class ChatServer(serialization.Serializable, log.Logger, log.LogProxy):
    classProvides(IChatServerFactory)
    implements(IChatServer, IConnectionAgent)

    def __init__(self, agent, port, client_disconnect_timeout=10):
        log.LogProxy.__init__(self, agent)
        log.Logger.__init__(self, self)

        self._agent = IConnectionAgent(agent)
        self._port = port

        # ChatProtocol instances
        self._connections = list()
        self._factory = ChatFactory(self, client_disconnect_timeout)
        self._listener = None

    ### IChatServer ###

    @property
    def port(self):
        return self._listener and self._listener.getHost().port

    @replay.side_effect
    def start(self):
        if self._listener:
            raise RuntimeError("start() already called, call stop first")
        self._listener = reactor.listenTCP(self._port, self._factory)

    @replay.side_effect
    def stop(self):
        if self._listener:
            self.debug('Stopping chat server.')
            self._listener.stopListening()
            for conn in self._connections:
                conn.disconnect()
            self._listener = None

    @replay.side_effect
    def get_list(self):
        resp = dict()
        for prot in self._connections:
            if prot.session_id:
                resp[prot.session_id] = prot.ip
        return resp

    @replay.side_effect
    def broadcast(self, body):
        for conn in self._connections:
            conn.send_msg(body)

    ### delegate IConnectionAgent for ChatFactory to use

    def validate_session(self, session_id):
        return self._agent.validate_session(session_id)

    def publish_message(self, body):
        self._agent.publish_message(body)
        self.broadcast(body)

    ### private interface for the use of ChatProtocol

    def connection_made(self, prot):
        self._connections.append(prot)

    def connection_lost(self, prot):
        if prot.session_id:
            self._agent.connection_lost(prot.session_id)
        self._connections.remove(prot)

    ### python specific ###

    def __eq__(self, other):
        if type(self) != type(other):
            return NotImplemented
        return self.port == other.port

    def __ne__(self, other):
        if type(self) != type(other):
            return NotImplemented
        return not self.__eq__(other)


class ChatFactory(protocol.ServerFactory):

    def __init__(self, server, client_disconnect_timeout=10):
        self.server = server
        self._client_disconnect_timeout = client_disconnect_timeout

    def buildProtocol(self, address):
        return ChatProtocol(self.server, address.host,
                            self._client_disconnect_timeout)


class ChatProtocol(basic.LineReceiver, log.Logger):

    delimeter = '\n'

    def __init__(self, server, ip, disconnect_timeout=10):
        log.Logger.__init__(self, server)
        self._server = server
        self._timeout = None
        self.session_id = None
        self.ip = ip

        self._disconnect_timeout = disconnect_timeout

    def lineReceived(self, line):
        if not line:
            return

        args = line.split(' ')
        cmd = args.pop(0)

        handler = "handle_%s" % (cmd, )
        method = getattr(self, handler, None)
        if not callable(method):
            self.debug('Uknown command %s. disconnecting' % (handler))
            self.disconnect()
            return

        method(" ".join(args))

    def connectionLost(self, reason):
        self._server.connection_lost(self)

    def connectionMade(self):
        self._server.connection_made(self)
        self._timeout = time.call_later(self._disconnect_timeout,
                                        self._verify_authorized)

    def _verify_authorized(self):
        if not self.session_id:
            self.disconnect()

    ### public ###

    def send_msg(self, body):
        if self.session_id:
            self.sendLine("msg %s" % body)

    def disconnect(self):
        self.log('Disconnecting client session_id: %r.', self.session_id)
        if self._timeout and self._timeout.active():
            self._timeout.cancel()
        if self._timeout:
            self._timeout = None
        self.transport.loseConnection()

    ### handlers ###

    def handle_session_id(self, session_id):
        if self.session_id:
            # second time?
            return

        if self._server.validate_session(session_id):
            self.session_id = session_id
        else:
            self.disconnect()

    def handle_msg(self, msg):
        if not self.session_id:
            self.disconnect()
            return
        self._server.publish_message(msg)

    def handle_quit(self, _=None):
        self.disconnect()
