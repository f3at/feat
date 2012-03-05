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
import uuid

from zope.interface import implements

from feat.agencies import document, recipient, message
from feat.agents.base import agent, partners, replay, poster, collector
from feat.agents.base import resource, contractor, dependency
from feat.agents.common import rpc, monitor
from feat.common import serialization, container

from feat.interface.agency import ExecMode
from feat.interface.protocols import InterestType
from feat.interface.collector import ICollectorFactory
from feat.interface.poster import IPosterFactory

from featchat.agents.connection import server
from featchat.application import featchat


@featchat.register_restorator
class RoomPartner(agent.BasePartner):

    def on_goodbye(self, agent):
        agent.call_next(agent.terminate)


class Partners(agent.Partners):

    partners.has_one('room', 'room_agent', RoomPartner)


@featchat.register_agent('connection_agent')
class ConnectionAgent(agent.BaseAgent, resource.AgentMixin):
    implements(server.IConnectionAgent)

    partners_class = Partners

    restart_strategy = monitor.RestartStrategy.buryme

    resources = {'chat': 1}

    dependency.register(server.IChatServerFactory,
                        server.DummyServer,
                        ExecMode.test)
    dependency.register(server.IChatServerFactory,
                        server.DummyServer,
                        ExecMode.simulation)
    dependency.register(server.IChatServerFactory,
                        server.ChatServer,
                        ExecMode.production)

    @replay.mutable
    def initiate(self, state):
        desc = state.medium.get_descriptor()
        config = state.medium.get_configuration()

        # define resource representing a connection
        state.resources.define('connections', resource.Scalar,
                              config.connections_limit)

        # contractor responsible for replying for new connection contractr
        self.register_interest(JoinContractor)
        # contractor responsible for fetching the list of connections and
        # terminating unnecessary connection agents
        self.register_interest(InspectAndTerminate)

        room_name = "room_%s" % (desc.name, )
        # poster which we will use for broadcasting messages sent by one of
        # our clients to other connection agents
        recp = recipient.Broadcast(room_name, 'lobby')
        state.room_poster = self.initiate_protocol(
            RoomPosterFactory(room_name), recp)
        # collector gathering messages comming from other connection agents
        interest = self.register_interest(RoomCollectorFactory(room_name))
        # after binding the interest to looby it can be accessed by
        # IRecpient(key=protocol_id, route='lobby')
        interest.bind_to_lobby()

        # session_id -> allocation_id represents preallocations
        state.pending_connections = container.ExpDict(state.medium)
        # session_id -> allocation_id represents allocated (authorized)
        # connections
        state.connections = dict()

        # initiate server dependency class
        port = list(desc.resources['chat'].values)[0]
        state.server = self.dependency(
            server.IChatServerFactory, self, port,
            client_disconnect_timeout=config.authorization_timeout)
        state.server.start()
        state.url = "%s:%d" % (state.medium.get_hostname(), port)

    @replay.journaled
    def startup(self, state):
        return self.startup_monitoring()

    @replay.journaled
    def on_killed(self, state):
        state.server.stop()

    @replay.journaled
    def shutdown(self, state):
        state.server.stop()

    ### public api ###

    @replay.journaled
    def get_list(self, state):
        res = state.server.get_list()
        # include pending connections as session_id -> None
        for session_id in state.pending_connections:
            res[session_id] = None
        return res

    @rpc.publish
    @replay.mutable
    def generate_join_url(self, state, allocation_id=None):
        session_id = self._generate_session_id()
        if allocation_id is None:
            al = self.preallocate_resource(connections=1)
            if al is None:
                raise resource.NotEnoughResource("not enough connection slots")
            allocation_id = al.id
        expiration = self.get_allocation_expiration(allocation_id)
        state.pending_connections.set(session_id, allocation_id, expiration)
        return dict(session_id=session_id, url=state.url)

    ### IConnectionAgent ###

    @replay.mutable
    def validate_session(self, state, session_id):
        allocation_id = state.pending_connections.pop(session_id, None)
        if not allocation_id:
            return False
        state.connections[session_id] = allocation_id
        self.call_next(self.confirm_allocation, allocation_id)
        return True

    @replay.immutable
    def publish_message(self, state, body):
        self.call_next(state.room_poster.notify, body=body)

    @replay.mutable
    def connection_lost(self, state, session_id):
        allocation_id = state.connections.pop(session_id, None)
        if allocation_id is None:
            self.warning("connection_lost() called for uknown session id: %r",
                         session_id)
            return
        self.call_next(self.release_resource, allocation_id)

    ### called when other agent notifies us with the message

    @replay.immutable
    def got_notification(self, state, body):
        state.server.broadcast(body)

    ### private ###

    @replay.side_effect
    def _generate_session_id(self):
        return str(uuid.uuid1())

    ### used for tests ###

    @replay.immutable
    def get_pending_connections(self, state):
        return state.pending_connections


class InspectAndTerminate(contractor.BaseContractor):
    '''
    This contractor is used by Room Agent to get and analize the list of
    connections. The list of connections (active and pending) is sent in
    bid message. Room Agent will grant the contract to connection agents
    which should be terminated. The strategy is to have at most one
    connection agent which does not have any connections.
    '''

    protocol_id = 'inspect-room'

    application = featchat

    @replay.mutable
    def announced(self, state, announcement):
        bid = message.Bid(payload=state.agent.get_list())
        state.medium.bid(bid)

    @replay.mutable
    def granted(self, state, grant):
        state.agent.terminate()
        state.medium.finalize(message.FinalReport())


class JoinContractor(contractor.BaseContractor):
    '''
    This contractor checks if we have enough resource to join accept
    another connection. If we have it preallocates it and generates session id.
    '''

    protocol_id = 'join-room'

    application = featchat

    @replay.journaled
    def announced(self, state, announce):
        al = state.agent.preallocate_resource(connections=1)
        state.allocation_id = al and al.id
        if al is None:
            refusal = message.Refusal()
            state.medium.refuse(refusal)
            return
        bid = message.Bid()
        # cost is number of left slots, as we want to favorize
        # fulling up existing agents
        totals, allocated = state.agent.list_resource()
        cost = totals['connections'] - allocated['connections']
        bid.payload = dict(cost=cost)
        state.medium.bid(bid)

    @replay.journaled
    def _release_allocation(self, state, *_):
        if state.allocation_id:
            return state.agent.release_resource(state.allocation_id)

    expired = _release_allocation
    rejected = _release_allocation
    cancelled = _release_allocation

    @replay.journaled
    def granted(self, state, grant):
        payload = state.agent.generate_join_url(state.allocation_id)
        report = message.FinalReport(payload=payload)
        state.medium.finalize(report)


@featchat.register_restorator
class ConnectionAgentConfiguration(document.Document):

    type_name = 'connection_agent_conf'
    document.field('doc_id', u'connection_agent_conf', '_id')
    document.field('connections_limit', 10)
    document.field('authorization_timeout', 10)

featchat.initial_data(ConnectionAgentConfiguration)


class RoomPoster(poster.BasePoster):

    application = featchat

    @replay.mutable
    def initiate(self, state):
        state.own_key = state.agent.get_own_address().key

    @replay.immutable
    def pack_payload(self, state, body):
        resp = dict()
        resp['key'] = state.own_key
        resp['body'] = body
        return resp


@featchat.register_restorator
class RoomPosterFactory(serialization.Serializable):
    '''
    The point of defining this class here (and RoomCollectorFactory below)
    is that we want to dynamically
    decide to protocol_id field for the interest and initiator. This is not
    typical use of the protocols - they usualy have this paramater fixed and
    set as a class attribute in Poster/Collector class.

    In our case we use multiple protocol_ids to have separate notifications
    for the different rooms.
    '''
    implements(IPosterFactory)

    def __init__(self, protocol_id):
        self.protocol_id = protocol_id
        self.protocol_type = RoomPoster.protocol_type

    def __call__(self, agent, medium):
        instance = RoomPoster(agent, medium)
        instance.protocol_id = self.protocol_id
        return instance


class RoomCollector(collector.BaseCollector):
    '''
    Every agent will have *one* instance of this class in his hamsterball.
    This is the interested part of the notification protocol. Every time
    the notification comes in the notified() method is called.
    '''

    application = featchat

    @replay.mutable
    def initiate(self, state):
        state.own_key = state.agent.get_own_address().key

    @replay.immutable
    def notified(self, state, notification):
        if notification.payload['key'] != state.own_key:
            state.agent.call_next(state.agent.got_notification,
                                  notification.payload['body'])


@featchat.register_restorator
class RoomCollectorFactory(serialization.Serializable):
    '''See doc for RoomPosterFactory for explanation.'''

    implements(ICollectorFactory)

    def __init__(self, protocol_id):
        # set protocol_id to desired value
        self.protocol_id = protocol_id
        # copy attributes defined in ICollectorFactory interface
        # namespace for protocol_id
        self.protocol_type = RoomCollector.protocol_type
        # public interest create extra binding to the shard exchange with the
        # routing key=protocol_id, moreover if this interest gets binded to
        # the 'lobby' we will create yet another binding making it globally
        # accesible
        self.interest_type = InterestType.public
        # the class type of the message with begins the dialog
        self.initiator = RoomCollector.initiator
        # how many concurrent instances are allowed (None=infinity)
        self.concurrency = None

    def __call__(self, agent, medium):
        instance = RoomCollector(agent, medium)
        instance.protocol_id = self.protocol_id
        return instance
