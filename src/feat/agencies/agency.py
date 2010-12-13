# -*- Mode: Python -*-
# vi:si:et:sw=4:sts=4:ts=4

import time
import uuid
import copy

from twisted.internet import reactor
from zope.interface import implements

from feat.common import log
from feat.agents.base import recipient
from feat.interface import agency, agent, protocols

from interface import IListener, IAgencyInitiatorFactory,\
                      IAgencyInterestedFactory, IConnectionFactory

from . import requests
from . import contracts


class Agency(object):
    implements(agency.IAgency)

    def __init__(self, messaging, database):
        self._agents = []
        # shard -> [ agents ]
        self._shards = {}

        self._messaging = IConnectionFactory(messaging)
        self._database = IConnectionFactory(database)

    def start_agent(self, factory, descriptor):
        factory = agent.IAgentFactory(factory)
        medium = AgencyAgent(self, factory, descriptor)
        self._agents.append(medium)
        return medium

    # TODO: Implement this, but first discuss what this really
    # means to unregister agent
    # def unregisterAgent(self, agent):
    #     self._agents.remove(agent)
    #     agent._messaging.disconnect()

    def joined_shard(self, agent, shard):
        shard_list = self._shards.get(shard, [])
        shard_list.append(agent)
        self._shards[shard] = shard_list

    def left_shard(self, agent, shard):
        shard_list = self._shards.get(shard, [])
        if agent in shard_list:
            shard_list.remove(agent)
        else:
            log.err('Was supposed to leave shard %r, but it was not there!' %\
                        shard)
        self._shards[shard] = shard_list

    def get_time(self):
        return time.time()


class AgencyAgent(log.FluLogKeeper, log.Logger):
    implements(agent.IAgencyAgent)

    log_category = "agency-agent"

    def __init__(self, aagency, factory, descriptor):

        log.FluLogKeeper.__init__(self)
        log.Logger.__init__(self, self)

        self.agency = agency.IAgency(aagency)
        self._descriptor = descriptor
        self.agent = factory(self)

        self._messaging = self.agency._messaging.get_connection(self)
        self._database = self.agency._database.get_connection(self)

        # instance_id -> IListener
        self._listeners = {}
        # protocol_type -> protocol_id -> protocols.IInterest
        self._interests = {}

        self.join_shard(descriptor.shard)
        self.agent.initiate()

    def get_descriptor(self):
        return copy.deepcopy(self._descriptor)

    def update_descriptor(self, desc):

        def update(desc):
            self.log("Updating descriptor: %r", desc)
            self._descriptor = desc

        d = self.save_document(desc)
        d.addCallback(update)
        return d

    def join_shard(self, shard):
        self.log("Join shard called. Shard: %r", shard)

        self.create_binding(self._descriptor.doc_id)
        self.agency.joined_shard(self, shard)

    def leave_shard(self, shard):
        bindings = self._messaging.get_bindings(shard)
        map(lambda binding: binding.revoke(), bindings)
        self.agency.left_shard(self, shard)

    def on_message(self, message):
        self.log('Received message: %r', message)

        # check if it isn't expired message
        ctime = self.get_time()
        if message.expiration_time < ctime:
            self.log('Throwing away expired message.')
            return False

        # handle registered dialog
        if message.session_id in self._listeners:
            listener = self._listeners[message.session_id]
            listener.on_message(message)
            return True

        # handle new conversation comming in (interest)
        p_type = message.protocol_type
        p_id = message.protocol_id
        if p_type in self._interests and p_id in self._interests[p_type] and\
          isinstance(message, self._interests[p_type][p_id].factory.initiator):
            self.log('Looking for interest to instantiate')
            factory = self._interests[message.protocol_type]\
                                     [message.protocol_id].factory
            medium_factory = IAgencyInterestedFactory(factory)
            medium = medium_factory(self, message)
            interested = factory(self.agent, medium)
            medium.initiate(interested)
            listener = self.register_listener(medium)
            listener.on_message(message)
            return True

        self.error("Couldn't find appriopriate listener for message: %s.%s",
                   message.protocol_type, message.protocol_id)
        return False

    def initiate_protocol(self, factory, recipients, *args, **kwargs):
        self.log('Initiating protocol for factory: %r, args: %r, kwargs: %r',
                 factory, args, kwargs)
        factory = protocols.IInitiatorFactory(factory)
        recipients = recipient.IRecipients(recipients)
        medium_factory = IAgencyInitiatorFactory(factory)
        medium = medium_factory(self, recipients, *args, **kwargs)

        initiator = factory(self.agent, medium, *args, **kwargs)
        self.register_listener(medium)
        return medium.initiate(initiator)

    def register_interest(self, factory):
        factory = protocols.IInterest(factory)
        p_type = factory.protocol_type
        p_id = factory.protocol_id
        if p_type not in self._interests:
            self._interests[p_type] = dict()
        if p_id in self._interests[p_type]:
            self.error('Already interested in %s.%s protocol!', p_type, p_id)
            return False
        self._interests[p_type][p_id] = Interest(self, factory)

        return True

    def revoke_interest(self, factory):
        factory = protocols.IInterest(factory)
        p_type = factory.protocol_type
        p_id = factory.protocol_id
        if p_type not in self._interests or\
           p_id not in self._interests[p_type]:
            self.error('Requested to revoke interest we are not interested in!'
                      ' %s.%s', p_type, p_id)
            return False
        self._interests[p_type][p_id].revoke()
        del(self._interests[p_type][p_id])

        return True

    def register_listener(self, listener):
        listener = IListener(listener)
        session_id = listener.get_session_id()
        self.debug('Registering listener session_id: %r', session_id)
        assert session_id not in self._listeners
        self._listeners[session_id] = listener
        return listener

    def unregister_listener(self, session_id):
        if session_id in self._listeners:
            self.debug('Unregistering listener session_id: %r', session_id)
            del(self._listeners[session_id])
        else:
            self.error('Tried to unregister listener with session_id: %r, '
                        'but not found!', session_id)

    def get_time(self):
        return self.agency.get_time()

    def send_msg(self, recipients, msg):
        recipients = recipient.IRecipients(recipients)
        msg.reply_to = recipient.IRecipient(self)
        msg.message_id = str(uuid.uuid1())
        assert msg.expiration_time is not None
        for recp in recipients:
            self.log('Sending message to %r', recp)
            self._messaging.publish(recp.key, recp.shard, msg)
        return msg

    def create_binding(self, key):
        return self._messaging.personal_binding(key)

    # Delegation of methods to IDatabaseClient

    def save_document(self, document):
        return self._database.save_document(document)

    def reload_document(self, document):
        return self._database.reload_document(document)

    def delete_document(self, document):
        return self._database.delete_document(document)

    def get_document(self, document_id):
        return self._database.get_document(document_id)


class Interest(object):
    '''Represents the interest from the point of view of agency.
    Manages the binding and stores factory reference'''

    factory = None
    binding = None

    def __init__(self, medium, factory):
        self.factory = factory

        if factory.interest_type == protocols.InterestType.public:
            self.binding = medium.create_binding(self.factory.protocol_id)

    def revoke(self):
        if self.factory.interest_type == protocols.InterestType.public:
            self.binding.revoke()
