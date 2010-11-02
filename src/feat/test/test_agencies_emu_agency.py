# -*- coding: utf-8 -*-
# -*- Mode: Python -*-
# vi:si:et:sw=4:sts=4:ts=4
import uuid, time

from zope.interface import classProvides, implements
from twisted.internet import reactor, defer

from feat.agencies.emu import agency
from feat.agents import agent, descriptor, requester, message, replier
from feat.interface import recipient, requests
from feat.interface.requester import IRequesterFactory
from feat.interface.replier import IReplierFactory, IAgentReplier

from . import common


class DummyRequester(requester.BaseRequester):
    classProvides(IRequesterFactory)

    protocol_id = 'dummy-request'
    timeout = 2

    def __init__(self, agent, medium, argument):
        requester.BaseRequester.__init__(self, agent, medium, argument)
        self.payload = argument
        self.got_response = False

    def initiate(self):
        msg = message.RequestMessage()
        msg.payload = self.payload
        self.medium.request(msg)

    def got_reply(self, message):
        self.got_response = True
        self.medium.terminate()


class DummyReplier(replier.BaseReplier):
    classProvides(IReplierFactory)
    implements(IAgentReplier)
    
    protocol_id = 'dummy-request'
    
    def requested(self, request):
        self.agent.got_payload = request.payload
        self.medium.reply(message.ResponseMessage())
        self.medium.terminate()


class TestAgencyAgent(common.TestCase):

    timeout = 3

    def setUp(self):
        self.agency = agency.Agency()
        desc = descriptor.Descriptor()
        self.agent = self.agency.start_agent(agent.BaseAgent, desc)

    def testJoinShard(self):
        self.assertEqual(1, len(self.agency._shards))
        self.assertEqual('lobby', self.agency._shards.keys()[0])
        self.assertEqual(1, len(self.agency._shards['lobby']))

        self.agent.leaveShard()
        self.assertEqual(1, len(self.agency._shards))
        self.assertEqual(0, len(self.agency._shards['lobby']))

    def testRequester(self):
        recipients = recipient.Agent('some_agent', 'lobby')
        d = self.agency.cb_on_msg('lobby', 'some_agent')
        payload = 5
        self.requester =\
            self.agent.initiate_protocol(DummyRequester, recipients, payload)

        def assertsOnMessage(message):
            self.assertEqual(self.agent.descriptor.shard, \
                             message.reply_to_shard)
            self.assertEqual(self.agent.descriptor.uuid, \
                             message.reply_to_key)
            self.assertEqual('Request', message.protocol_type)
            self.assertEqual('dummy-request', message.protocol_id)
            self.assertEqual(payload, message.payload)
            self.assertTrue(message.expiration_time is not None)

            session_id = message.session_id
            self.assertEqual(session_id, str(session_id))

            self.assertEqual(requests.RequestState.requested,\
                                 self.requester.state)
            return session_id

        d.addCallback(assertsOnMessage)

        def assertsOnAgency(session_id):
            self.log('%r', self.agent._listeners.keys())
            self.assertTrue(session_id in self.agent._listeners.keys())
            listener = self.agent._listeners[session_id]
            self.assertEqual('AgencyRequester', listener.__class__.__name__)
            return session_id

        d.addCallback(assertsOnAgency)

        def mimicReceivingResponse(session_id):
            response = message.ResponseMessage()
            response.session_id = session_id
            response.expiration_time = self.requester.request.expiration_time

            key, shard = self.agent.descriptor.uuid, self.agent.descriptor.shard
            self.agent._messaging.publish(key, shard, response)
            return session_id

        d.addCallback(mimicReceivingResponse)
        d.addCallback(self.cb_after, \
                      obj=self.agent, method='unregister_listener')

        def assertGotResponseAndTerminated(session_id):
            self.assertFalse(session_id in self.agent._listeners.keys())
            self.assertTrue(self.requester.got_response)

        d.addCallback(assertGotResponseAndTerminated)

        return d


    def testRequestTimeout(self):
        self.agency.time_scale = 0.01

        recipients = recipient.Agent('some_agent', 'lobby')
        d = self.agency.cb_on_msg('lobby', 'some_agent')
        payload = 5
        self.requester =\
            self.agent.initiate_protocol(DummyRequester, recipients, payload)

        d.addCallback(self.cb_after, obj=self.agent,
                      method='unregister_listener')

        def assertTerminatedWithNoResponse(_):
            session_id = self.requester.medium.session_id
            self.assertFalse(session_id in self.agent._listeners.keys())
            self.assertFalse(self.requester.got_response)
            self.assertEqual(requests.RequestState.closed, self.requester.state)

        d.addCallback(assertTerminatedWithNoResponse)

        return d

    def testRegisteringAndRevokeReplier(self):
        self.agent.register_interest(DummyReplier)

        self.assertTrue('Request' in self.agent._interests)
        self.assertTrue('dummy-request' in self.agent._interests['Request'])

        self.agent.revoke_interest(DummyReplier)
        self.assertFalse('dummy-request' in self.agent._interests['Request'])

        #calling once again nothing bad should happend
        req = self.agent.revoke_interest(DummyReplier)
        self.assertFalse(req)

    def testReplierReplies(self):
        self.agent.register_interest(DummyReplier)

        shard = self.agent.descriptor.shard
        key = self.agent.descriptor.uuid
        # define false sender, he will get the response later
        recp = recipient.Agent(str(uuid.uuid1()), shard)
        d = self.agency.cb_on_msg(shard, recp.key)
        req = self._build_req_msg(recp)
        self.agency._messaging.publish(key, recp.shard, req)

        def assert_on_msg(msg):
            self.assertEqual('dummy-request', msg.protocol_id)
            self.assertEqual(req.session_id, msg.session_id)
            
        d.addCallback(assert_on_msg)

        return d

    def testGetingRequestWithoutInterest(self):
        '''Current implementation just ignores such events. Update this test
        in case we decide to do sth else'''
        d = self.cb_after(arg=None, obj=self.agent, method='on_message')

        shard = self.agent.descriptor.shard
        key = self.agent.descriptor.uuid
        recp = recipient.Agent(str(uuid.uuid1()), shard)
        req = self._build_req_msg(recp)
        self.agency._messaging.publish(key, recp.shard, req)

        # wait for the message to be processed
        return d

    def testNotProcessingExpiredRequests(self):
        self.agent.register_interest(DummyReplier)
        self.agent.agent.got_payload = False
        d = self.cb_after(arg=None, obj=self.agent, method='on_message')

        shard = self.agent.descriptor.shard
        key = self.agent.descriptor.uuid
        # define false sender, he will get the response later
        recp = recipient.Agent(str(uuid.uuid1()), shard)
        req = self._build_req_msg(recp)
        req.expiration_time = time.time() - 1

        self.agency._messaging.publish(key, recp.shard, req)
        
        def asserts_after_procesing(return_value):
            self.assertFalse(return_value)
            self.assertEqual(False, self.agent.agent.got_payload)

        d.addCallback(asserts_after_procesing)
        
        return d
        
    def testTwoAgentsTalking(self):
        receiver = self.agent
        sender = self.agency.start_agent(agent.BaseAgent,
                                         descriptor.Descriptor())
        receiver.register_interest(DummyReplier)
        requester = sender.initiate_protocol(DummyRequester, receiver, 1)

        d = self.cb_after(arg=requester,
                          obj=requester.medium, method='terminate')

        def asserts_on_requester(requester):
            self.assertTrue(requester.got_response)
            self.assertEqual(0, len(sender._listeners))

        d.addCallback(asserts_on_requester)
        
        def asserts_on_receiver(_, receiver):
            self.assertEqual(0, len(receiver._listeners))
            self.assertEqual(1, receiver.agent.got_payload)

        d.addCallback(asserts_on_receiver, receiver)

        return d

    def _build_req_msg(self, recp):
        r = message.RequestMessage()
        r.message_id = str(uuid.uuid1())
        r.session_id = str(uuid.uuid1())
        r.expiration_time = time.time() + 10
        r.protocol_type = 'Request'
        r.protocol_id = 'dummy-request'
        r.reply_to_key = recp.key
        r.reply_to_shard = recp.shard
        r.payload = 10
        return r
