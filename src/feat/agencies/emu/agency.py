# -*- Mode: Python -*-
# vi:si:et:sw=4:sts=4:ts=4

import time
import uuid

from twisted.python import components
from twisted.internet import reactor
from zope.interface import implements, Interface

from feat.common import log
from feat.interface.agency import IAgency
from feat.interface.agent import IAgencyAgent, IAgentFactory
from feat.interface.protocols import IInitiatorFactory,\
                                     IAgencyInitiatorFactory,\
                                     IInterest,\
                                     IAgencyInterestedFactory
from feat.interface.requester import IAgencyRequester, IRequesterFactory,\
                                     IAgentRequester
from feat.interface.replier import IAgencyReplier, IAgentReplier,\
                                   IReplierFactory
from feat.interface.contractor import IAgencyContractor, IAgentContractor,\
                                      IContractorFactory
from feat.interface import recipient, requests, contracts
from feat.agents import message

from . import messaging
from . import database



class Agency(object):
    implements(IAgency)

    time_scale = 1

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

    # TODO: Implement this, but first discuss what this really
    # means to unregister agent
    # def unregisterAgent(self, agent):
    #     self._agents.remove(agent)
    #     agent._messaging.disconnect()

    def callLater(self, timeout, method, *args, **kwargs):
        return reactor.callLater(self.time_scale * timeout,\
                                     method, *args, **kwargs)

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

    def get_time(self):
        return time.time()

    # FOR TESTS
    def cb_on_msg(self, shard, key):
        m = self._messaging
        queue = m.defineQueue(name=str(uuid.uuid1()))
        exchange = m._getExchange(shard)
        exchange.bind(key, queue)
        return queue.consume()


class AgencyAgent(log.FluLogKeeper, log.Logger):
    implements(IAgencyAgent)

    log_category = "agency-agent"

    def __init__(self, agency, factory, descriptor):

        log.FluLogKeeper.__init__(self)
        log.Logger.__init__(self, self)

        self.agency = IAgency(agency)
        self.descriptor = descriptor
        self.agent = factory(self)

        self._messaging = agency._messaging.createConnection(self)
        self._database = agency._database

        # instance_id -> IListener
        self._listeners = {}
        # protocol_type -> protocol_key -> IInterest
        self._interests = {}

        self.joinShard()
        self.agent.initiate()

    def callLater(self, timeout, method, *args, **kwargs):
        return self.agency.callLater(timeout, method, *args, **kwargs)

    def joinShard(self):
        self.log("Join shard called")
        shard = self.descriptor.shard
        self._messaging.createPersonalBinding(self.descriptor.uuid, shard)
        self.agency.joinedShard(self, shard)

    def leaveShard(self):
        bindings = self._messaging.getBindingsForShard(self.descriptor.shard)
        map(lambda binding: binding.revoke(), bindings)
        self.agency.leftShard(self, self.descriptor.shard)
        self.descriptor.shard = None

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
        if message.protocol_type in self._interests and\
           message.protocol_id in self._interests[message.protocol_type]:
            self.log('Looking for interest to instantiate')
            factory = self._interests[message.protocol_type]\
                                     [message.protocol_id]
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
        factory = IInitiatorFactory(factory)
        recipients = recipient.IRecipient(recipients)
        medium_factory = IAgencyInitiatorFactory(factory)
        medium = medium_factory(self, recipients, *args, **kwargs)

        initiator = factory(self.agent, medium, *args, **kwargs)
        self.register_listener(medium)
        return medium.initiate(initiator)

    def register_interest(self, factory):
        factory = IInterest(factory)
        p_type = factory.protocol_type
        p_id = factory.protocol_id
        if p_type not in self._interests:
            self._interests[p_type] = dict()
        if p_id in self._interests[p_type]:
            self.error('Already interested in %s.%s protocol!', p_type, p_id)
            return False
        self._interests[p_type][p_id] = factory
        return True

    def revoke_interest(self, factory):
        factory = IInterest(factory)
        p_type = factory.protocol_type
        p_id = factory.protocol_id
        if p_type not in self._interests or\
           p_id not in self._interests[p_type]:
           self.error('Requested to revoke interest we are not interested in!'
                      ' %s.%s', p_type, p_id)
           return False
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
            self.error('Tried to unregister listener with session_id: %r,\
                        but not found!', session_id)

    def get_time(self):
        return self.agency.get_time()

    def send_msg(self, recipients, msg):
        recipients = recipient.IRecipient(recipients)
        msg.reply_to_shard = self.descriptor.shard
        msg.reply_to_key = self.descriptor.uuid
        msg.message_id = str(uuid.uuid1())
        assert msg.expiration_time is not None
        self._messaging.publish(recipients.key, recipients.shard, msg)
        return msg


class AgencyRequesterFactory(object):
    implements(IAgencyInitiatorFactory)

    def __init__(self, factory):
        self._factory = factory

    def __call__(self, agent, recipients, *args, **kwargs):
        return AgencyRequester(agent, recipients, *args, **kwargs)


components.registerAdapter(AgencyRequesterFactory,
                           IRequesterFactory, IAgencyInitiatorFactory)


class IListener(Interface):
    '''Represents sth which can be registered in AgencyAgent to
    listen for message'''

    def on_message(message):
        '''hook called when message arrives'''

    def get_session_id():
        '''
        @return: session_id to bound to
        @rtype: string
        '''

class AgencyRequester(log.LogProxy, log.Logger):
    implements(IAgencyRequester, IListener)

    log_category = 'agency-requester'

    def __init__(self, agent, recipients, *args, **kwargs):
        log.Logger.__init__(self, agent)
        log.LogProxy.__init__(self, agent)

        self.agent = agent
        self.recipients = recipients
        self.session_id = str(uuid.uuid1())
        self.log_name = self.session_id
        self.closed_call = None

    def initiate(self, requester):
        self.requester = requester
        if requester.timeout > 0:
            self.closed_call = self.agent.callLater(requester.timeout,
                                                    self.expired)
        requester.state = requests.RequestState.requested
        requester.initiate()

        return requester

    def expired(self):
        self.requester.closed()
        self.terminate()

    def request(self, request):
        self.debug("Sending request")
        request.session_id = self.session_id
        request.protocol_id = self.requester.protocol_id
        if self.requester.timeout > 0:
            request.expiration_time =\
                self.agent.get_time() + self.requester.timeout

        self.requester.request = self.agent.send_msg(self.recipients, request)
        
    def terminate(self):
        self.debug('Terminate called')
        self.requester.state = requests.RequestState.closed
        self.agent.unregister_listener(self.session_id)

    # IListener stuff

    def on_message(self, message):
        if self.closed_call:
            self.closed_call.cancel()
        self.requester.got_reply(message)

    def get_session_id(self):
        return self.session_id


class AgencyReplierFactory(object):
    implements(IAgencyInterestedFactory)

    def __init__(self, factory):
        self._factory = factory

    def __call__(self, agent, message):
        return AgencyReplier(agent, message)


components.registerAdapter(AgencyReplierFactory,
                           IReplierFactory, IAgencyInterestedFactory)


class AgencyReplier(log.LogProxy, log.Logger):
    implements(IAgencyReplier, IListener)
 
    log_category = 'agency-replier'

    def __init__(self, agent, message):
        log.Logger.__init__(self, agent)
        log.LogProxy.__init__(self, agent)

        self.agent = agent
        self.request = message
        self.recipients = recipient.Agent(message.reply_to_key,
                                          message.reply_to_shard)
        self.session_id = message.session_id
        self.protocol_id = message.protocol_id

        self.log_name = self.session_id
        self.message_count = 0

    def initiate(self, replier):
        self.replier = replier
        return replier
    
    def reply(self, reply):
        self.debug("Sending reply")
        reply.session_id = self.session_id
        reply.protocol_id = self.protocol_id
        reply.expiration_time = self.request.expiration_time

        self.agent.send_msg(self.recipients, reply)
        
    def terminate(self):
        self.debug('Terminate called')
        self.agent.unregister_listener(self.session_id)

    # IListener stuff

    def on_message(self, message):
        self.message_count += 1
        if self.message_count == 1:
            self.replier.requested(message)
        else:
            self.error("Got unexpected message: %r", message)

    def get_session_id(self):
        return self.session_id


class AgencyContractorFactory(object):
    implements(IAgencyInterestedFactory)

    def __init__(self, factory):
        self._factory = factory

    def __call__(self, agent, recipients, *args, **kwargs):
        return AgencyContractor(agent, recipients, *args, **kwargs)


components.registerAdapter(AgencyContractorFactory,
                           IContractorFactory, IAgencyInterestedFactory)


class AgencyContractor(log.LogProxy, log.Logger):
    implements(IAgencyContractor, IListener)
 
    log_category = 'agency-contractor'

    def __init__(self, agent, announcement):
        log.Logger.__init__(self, agent)
        log.LogProxy.__init__(self, agent)

        assert isinstance(announcement, message.Announcement)

        self.agent = agent
        self.announce = announcement
        self.recipients = recipient.Agent(announcement.reply_to_key,
                                          announcement.reply_to_shard)
        self.session_id = announcement.session_id
        self.protocol_id = announcement.protocol_id

        self.log_name = self.session_id

    def initiate(self, contractor):
        self.contractor = contractor
        self.contractor.state = contracts.ContractState.announced
        return contractor

    def bid(self, bid):
        self.debug("Sending bid %r", bid)
        assert isinstance(bid, message.Bid)
        assert isinstance(bid.bids, list)
        self.bid = self._send_message(bid)
        self.contractor.state = contracts.ContractState.bid
        return self.bid
        
    def refuse(self, refusal):
        self.debug("Sending refusal %r", refusal)
        assert isinstance(refusal, message.Refusal)
        refusal = self._send_message(refusal)
        self.contractor.state = contracts.ContractState.rejected
        return refusal

    def cancel(self, cancellation):
        self.debug("Sending cancelation %r", cancellation)
        assert isinstance(cancellation, message.Cancellation)
        cancellation = self._send_message(cancellation)
        self.contractor.state = contracts.ContractState.aborted
        return cancellation

    def update(self, report):
        self.debug("Sending update report %r", report)
        assert isinstance(report, message.UpdateReport)
        report = self._send_message(self, report)
        return report

    def finalize(self, report):
        self.debug("Sending final report %r", report)
        assert isinstance(report, message.FinalReport)
        self.report = self._send_message(self, report)
        return self.report
    
    # private section

    def _send_message(self, msg):
        msg.session_id = self.session_id
        msg.protocol_id = self.protocol_id
        msg.expiration_time = self.request.expiration_time

        return self.agent.send_msg(self.recipients, msg)

    def _validate_bid(self, grant):
        '''
        Called upon receiving the grant. Check that grants bid includes
        actual bid we put. Than calls granted and sets up reporter if necessary.
        '''
        is_ok = grant.bid in self.bid.bids
        if is_ok:
            self.grant = grant
            self.contractor.granted(grant)
            if grant.update_report:
                self._setup_reported()
        else:
            self.error("The bid granted doesn't much put upon! Terminating!")
            self.error("Bid: %r, bids: %r", grant.bid, self.bid.bids)
            self._terminate()

    def _terminate(self):
        self.log("Unregistering contractor")
        self.agent.unregister_listener(self.session_id)

    def _ack_and_terminate(self, msg):
        self.contractor.acknowledged(msg)
        self._terminate()

    # IListener stuff

    def on_message(self, msg):
        mapping = {
            message.Announcemnt: { 'method': self.contractor.announced },
            message.Rejection: { 'method': self.contractor.rejected,
                                 'state': contracts.ContractState.rejected },
            message.Grant: { 'method': self._validate_bid },
            message.Cancellation: { 'method': self.contractor.canceled,
                                    'state': contracts.ContractState.aborted },
            message.Acknowledged: { 'method': self._ack_and_terminate,
                                'state': contracts.ContractState.acknowledged},
        }
        klass = msg.__class__
        decision = mapping.get(klass, None)
        if not decision:
            self.error("Unknown method class %r", msg)
            return False

        change_state = decision.get('state', None)
        if change_state:
            self.contractor.state = change_state

        decision['method'](msg)

    def get_session_id(self):
        return self.session_id
