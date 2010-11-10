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


class TestAgencyAgent(common.TestCase, common.AgencyTestHelper):

    timeout = 3
    protocol_type = 'Request'
    protocol_id = 'dummy-request'

    def setUp(self):
        common.AgencyTestHelper.setUp(self)
        
        desc = descriptor.Descriptor()
        self.agent = self.agency.start_agent(agent.BaseAgent, desc)

        self.queue, self.endpoint = self._setup_endpoint()

    def testJoinShard(self):
        self.assertEqual(1, len(self.agency._shards))
        self.assertEqual('lobby', self.agency._shards.keys()[0])
        self.assertEqual(1, len(self.agency._shards['lobby']))

        self.agent.leaveShard()
        self.assertEqual(1, len(self.agency._shards))
        self.assertEqual(0, len(self.agency._shards['lobby']))

    def testRegisteringAndRevokeReplier(self):
        self.agent.register_interest(DummyReplier)

        self.assertTrue('Request' in self.agent._interests)
        self.assertTrue('dummy-request' in self.agent._interests['Request'])

        self.agent.revoke_interest(DummyReplier)
        self.assertFalse('dummy-request' in self.agent._interests['Request'])

        #calling once again nothing bad should happend
        req = self.agent.revoke_interest(DummyReplier)
        self.assertFalse(req)

    def testGetingRequestWithoutInterest(self):
        '''Current implementation just ignores such events. Update this test
        in case we decide to do sth else'''
        key = self.agent.descriptor.uuid
        msg = message.RequestMessage()
        msg.session_id = str(uuid.uuid1())
        return self._recv_msg(msg, self.endpoint, key)


class TestRequests(common.TestCase, common.AgencyTestHelper):

    timeout = 3

    protocol_type = 'Request'
    protocol_id = 'dummy-request'

    def setUp(self):
        common.AgencyTestHelper.setUp(self)
        
        desc = descriptor.Descriptor()
        self.agent = self.agency.start_agent(agent.BaseAgent, desc)

        self.endpoint, self.queue = self._setup_endpoint()

    def testRequester(self):

        d = self.queue.consume()
        payload = 5
        self.requester =\
            self.agent.initiate_protocol(DummyRequester, self.endpoint, payload)

        def assertsOnMessage(message):
            self.assertEqual(self.agent.descriptor.shard, \
                             message.reply_to.shard)
            self.assertEqual(self.agent.descriptor.uuid, \
                             message.reply_to.key)
            self.assertEqual('Request', message.protocol_type)
            self.assertEqual('dummy-request', message.protocol_id)
            self.assertEqual(payload, message.payload)
            self.assertTrue(message.expiration_time is not None)

            session_id = message.session_id
            self.assertEqual(session_id, str(session_id))

            self.assertEqual(requests.RequestState.requested,\
                                 self.requester.medium.state)
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
            self._reply(response, self.endpoint, self.requester.request)

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

        d = self.queue.consume()
        payload = 5
        self.requester =\
            self.agent.initiate_protocol(DummyRequester, self.endpoint, payload)

        d.addCallback(self.cb_after, obj=self.agent,
                      method='unregister_listener')

        def assertTerminatedWithNoResponse(_):
            session_id = self.requester.medium.session_id
            self.assertFalse(session_id in self.agent._listeners.keys())
            self.assertFalse(self.requester.got_response)
            self.assertEqual(requests.RequestState.closed,
                             self.requester.medium.state)

        d.addCallback(assertTerminatedWithNoResponse)

        return d

    def testReplierReplies(self):
        self.agent.register_interest(DummyReplier)

        key = self.agent.descriptor.uuid

        req = self._build_req_msg(self.endpoint)
        d = self._recv_msg(req, self.endpoint, key)

        d.addCallback(lambda _: self.queue.consume())
        
        def assert_on_msg(msg):
            self.assertEqual('dummy-request', msg.protocol_id)
            self.assertEqual(req.session_id, msg.session_id)
            
        d.addCallback(assert_on_msg)

        return d

    def testNotProcessingExpiredRequests(self):
        self.agent.register_interest(DummyReplier)
        self.agent.agent.got_payload = False

        key = self.agent.descriptor.uuid
        # define false sender, he will get the response later
        req = self._build_req_msg(self.endpoint)
        expiration_time = time.time() - 1
        d = self._recv_msg(req, self.endpoint, key, expiration_time)

        def asserts_after_procesing(return_value):
            self.log(return_value)
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
        r.session_id = str(uuid.uuid1())
        r.payload = 10
        return r
