# -*- Mode: Python -*-
# vi:si:et:sw=4:sts=4:ts=4

import messaging
import database
from twisted.python import log, components
from feat.interface.agent import IAgencyAgent, IAgentFactory
from feat.interface.agency import IAgency
from feat.interface.protocols import IInitiatorFactory,\
                                     IAgencyInitiatorFactory,\
                                     IListener
from feat.interface.requester import IAgencyRequester, IRequesterFactory
from zope.interface import implements, classProvides

import uuid

class Agency(object):
    implements(IAgency)
    
    def __init__(self):
        self._agents = []
        # shard -> [ agents ]
        self._shards = {}

        self._messaging = messaging.Messaging()
        self._database = database.Database()

    def start_agent(self, factory, descriptor):
        factory = IAgentFactory(factory)
        medium = AgencyAgent(self, factory, descriptor)
        self._agents.append(medium)
        return medium

    def unregisterAgent(self, agent):
        self._agents.remove(agent)
        agent._messaging.disconnect()

    def joinedShard(self, agent, shard):
        shard_list = self._shards.get(shard, [])
        shard_list.append(agent)
        self._shards[shard] = shard_list

    def leftShard(self, agent, shard):
        shard_list = self._shards.get(shard, [])
        if agent in shard_list:
            shard_list.remove(agent)
        else:
            log.err('Was supposed to leave shard %r, but it was not there!' %\
                        shard)
        self._shards[shard] = shard_list

    # FOR TESTS
    def callbackOnMessage(self, shard, key):
        m = self._messaging
        queue = m.defineQueue(name=uuid.uuid1())
        exchange = m._getExchange(shard)
        exchange.bind(key, queue)
        return queue.consume()





class AgencyAgent(object):
    implements(IAgencyAgent)

    def __init__(self, agency, factory, descriptor):
        
        self.agency = IAgency(agency)
        self.descriptor = descriptor
        self.agent = factory(self)

        self._messaging = agency._messaging.createConnection(self)
        self._database = agency._database

        # instance_id -> IListener
        self._listeners = {}
        # contract_type -> IListenerFactory
        self._listener_factories = []

        self.joinShard()
        self.agent.initiate()
        
    def joinShard(self):
        shard = self.descriptor.shard
        self._messaging.createPersonalBinding(self.descriptor.uuid, shard)
        self.agency.joinedShard(self, shard)

    def leaveShard(self):
        bindings = self._messaging.getBindingsForShard(self.descriptor.shard)
        map(lambda binding: binding.revoke(), bindings)
        self.agency.leftShard(self, self.descriptor.shard)
        self.descriptor.shard = None
        
    def on_message(self, message):
        if message.session_id in self._listeners:
            listener = self._listeners[session_id]
            return listener.on_message(message)
            
        if message.protocol_id in self._listener_factoriers:
            factory = self._listener_factories[message.protocol_id]
            self.create_listener_instance(factory, message.instance_id)

    def initiate_protocol(self, factory, recipients, *args, **kwargs):
        factory = IInitiatorFactory(factory)
        medium_factory = IAgencyInitiatorFactory(factory)
        medium = medium_factory(self, recipients, *args, **kwargs)

        initiator = factory(self, medium, *args, **kwargs)
        self.register_listener(initiator)
        initiator.initiate()

    def register_listener(self, listener):
        listener = IListener(listener)
        session_id = listener.get_session_id()
        assert session_id not in self._listeners

        self._listeners[session_id] = listener


class AgencyRequesterFactory(object):
    implements(IAgencyInitiatorFactory)

    def __init__(self, factory):
        self._factory = factory

    def __call__(self, agent, recipients, *args, **kwargs):
        return AgencyRequester(agent, recipients, *args, **kwargs)
        

class AgencyRequester(object):
    implements(IAgencyRequester)

    def __init__(self, agent, recipients, *args, **kwargs):
        self.agent = agent
        self.recipients = recipients
        self.session_id = uuid.uuid1()

    def request(self, request):
        request.session_id = self.session_id
        self.reply_to_shard = self.agent.descriptor.shard
        self.reply_to_key = self.agent.descriptor.uuid

        self.agent._messaging.publish(self.recipients.key,\
                                      self.recipients.shard, request)


components.registerAdapter(AgencyRequesterFactory,
                           IRequesterFactory, IAgencyInitiatorFactory)
