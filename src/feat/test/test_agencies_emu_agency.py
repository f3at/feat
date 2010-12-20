# -*- coding: utf-8 -*-
# -*- Mode: Python -*-
# vi:si:et:sw=4:sts=4:ts=4
import uuid
import time

from zope.interface import classProvides, implements
from twisted.internet import defer

from feat.agents.base import agent, descriptor, requester, message, replier
from feat.interface import requests, protocols
from feat.interface.requester import IRequesterFactory
from feat.interface.replier import IReplierFactory, IAgentReplier
from feat.common import delay

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

    @defer.inlineCallbacks
    def setUp(self):
        common.AgencyTestHelper.setUp(self)

        desc = yield self.doc_factory(descriptor.Descriptor)
        self.agent = yield self.agency.start_agent(desc)

        self.queue, self.endpoint = self.setup_endpoint()

    def testJoinShard(self):
        self.assertEqual(1, len(self.agency._shards))
        self.assertEqual('lobby', self.agency._shards.keys()[0])
        self.assertEqual(1, len(self.agency._shards['lobby']))

        self.agent.leave_shard('lobby')
        self.assertEqual(1, len(self.agency._shards))
        self.assertEqual(0, len(self.agency._shards['lobby']))

    @defer.inlineCallbacks
    def testUpdateDocument(self):
        desc = self.agent.get_descriptor()
        self.assertIsInstance(desc, descriptor.Descriptor)

        desc.shard = 'changed'
        yield self.agent.update_descriptor(desc)
        self.assertEqual('changed', self.agent._descriptor.shard)

    def testRegisterTwice(self):
        self.assertTrue(self.agent.register_interest(DummyReplier))
        self.failIf(self.agent.register_interest(DummyReplier))

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
        key = (self.agent.get_descriptor()).doc_id
        msg = message.RequestMessage()
        msg.session_id = str(uuid.uuid1())
        return self.recv_msg(msg, self.endpoint, key)


class TestRequests(common.TestCase, common.AgencyTestHelper):

    timeout = 3

    protocol_type = 'Request'
    protocol_id = 'dummy-request'

    @defer.inlineCallbacks
    def setUp(self):
        common.AgencyTestHelper.setUp(self)

        desc = yield self.doc_factory(descriptor.Descriptor)
        self.agent = yield self.agency.start_agent(desc)

        self.endpoint, self.queue = self.setup_endpoint()

    def testRequester(self):

        d = self.queue.get()
        payload = 5
        self.finished =\
            self.agent.initiate_protocol(DummyRequester,
                                         self.endpoint, payload)
        self.assertIsInstance(self.finished, defer.Deferred)
        self.requester = (self.agent._listeners.values()[0]).requester

        def assertsOnMessage(message):
            desc = self.agent.get_descriptor()
            self.assertEqual(desc.shard, \
                             message.reply_to.shard)
            self.assertEqual(desc.doc_id, \
                             message.reply_to.key)
            self.assertEqual('Request', message.protocol_type)
            self.assertEqual('dummy-request', message.protocol_id)
            self.assertEqual(payload, message.payload)
            self.assertTrue(message.expiration_time is not None)

            session_id = message.sender_id
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
            self.reply(response, self.endpoint, self.requester.request)

            return session_id

        d.addCallback(mimicReceivingResponse)
        d.addCallback(lambda _: self.finished)

        def assertGotResponseAndTerminated(session_id):
            self.assertFalse(session_id in self.agent._listeners.keys())
            self.assertTrue(self.requester.got_response)

        d.addCallback(assertGotResponseAndTerminated)

        return d

    def testRequestTimeout(self):
        delay.time_scale = 0.01

        d = self.queue.get()
        payload = 5
        self.finished =\
            self.agent.initiate_protocol(DummyRequester,
                                         self.endpoint, payload)
        self.assertFailure(self.finished, protocols.InitiatorFailed)

        self.requester = (self.agent._listeners.values()[0]).requester

        d.addCallback(self.cb_after, obj=self.agent,
                      method='unregister_listener')

        def assertTerminatedWithNoResponse(_):
            session_id = self.requester.medium.session_id
            self.assertFalse(session_id in self.agent._listeners.keys())
            self.assertFalse(self.requester.got_response)
            self.assertEqual(requests.RequestState.closed,
                             self.requester.medium.state)

        d.addCallback(assertTerminatedWithNoResponse)
        d.addCallback(lambda _: self.finished)

        return d

    def testReplierReplies(self):
        self.agent.register_interest(DummyReplier)

        key = (self.agent.get_descriptor()).doc_id

        req = self._build_req_msg(self.endpoint)
        d = self.recv_msg(req, self.endpoint, key)

        d.addCallback(lambda _: self.queue.get())

        def assert_on_msg(msg):
            self.assertEqual('dummy-request', msg.protocol_id)

        d.addCallback(assert_on_msg)

        return d

    def testNotProcessingExpiredRequests(self):
        self.agent.register_interest(DummyReplier)
        self.agent.agent.got_payload = False

        key = (self.agent.get_descriptor()).doc_id
        # define false sender, he will get the response later
        req = self._build_req_msg(self.endpoint)
        expiration_time = time.time() - 1
        d = self.recv_msg(req, self.endpoint, key, expiration_time)

        def asserts_after_procesing(return_value):
            self.log(return_value)
            self.assertFalse(return_value)
            self.assertEqual(False, self.agent.agent.got_payload)

        d.addCallback(asserts_after_procesing)

        return d

    @defer.inlineCallbacks
    def testTwoAgentsTalking(self):
        receiver = self.agent
        desc = yield self.doc_factory(descriptor.Descriptor)
        sender = yield self.agency.start_agent(desc)

        receiver.register_interest(DummyReplier)
        self.finished =\
            sender.initiate_protocol(DummyRequester,
                                         receiver, 1)
        requester = (sender._listeners.values()[0]).requester

        yield self.cb_after(arg=requester,
                          obj=requester.medium, method='_terminate')

        self.assertTrue(requester.got_response)
        self.assertEqual(0, len(sender._listeners))

        self.assertEqual(0, len(receiver._listeners))
        self.assertEqual(1, receiver.agent.got_payload)

    def _build_req_msg(self, recp):
        r = message.RequestMessage()
        r.session_id = str(uuid.uuid1())
        r.payload = 10
        return r
