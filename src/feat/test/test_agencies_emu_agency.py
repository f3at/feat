# -*- coding: utf-8 -*-
# -*- Mode: Python -*-
# vi:si:et:sw=4:sts=4:ts=4
import uuid
import time

from twisted.internet import defer

from feat.agents.base import descriptor, requester, message, replier, replay
from feat.interface import requests, protocols
from feat.common import delay, log
from feat.agencies import agency
from feat.agencies.interface import NotFoundError

from . import common


class DummyRequester(requester.BaseRequester):

    protocol_id = 'dummy-request'
    timeout = 2

    def init_state(self, state, agent, medium, argument):
        requester.BaseRequester.init_state(
            self, state, agent, medium, argument)
        state.payload = argument
        state._got_response = False

    @replay.immutable
    def initiate(self, state):
        msg = message.RequestMessage()
        msg.payload = state.payload
        state.medium.request(msg)

    @replay.immutable
    def got_reply(self, state, message):
        state._got_response = True

    @replay.immutable
    def _get_medium(self, state):
        self.log(state)
        return state.medium

    @replay.immutable
    def got_response(self, state):
        return state._got_response


class DummyReplier(replier.BaseReplier):

    protocol_id = 'dummy-request'

    @replay.immutable
    def requested(self, state, request):
        state.agent.got_payload = request.payload
        state.medium.reply(message.ResponseMessage())


class TestAgencyAgent(common.TestCase, common.AgencyTestHelper):

    timeout = 3
    protocol_type = 'Request'
    protocol_id = 'dummy-request'

    @defer.inlineCallbacks
    def setUp(self):
        common.AgencyTestHelper.setUp(self)

        desc = yield self.doc_factory(descriptor.Descriptor)
        self.agent = yield self.agency.start_agent(desc)

        self.endpoint, self.queue = self.setup_endpoint()

    def testJoinShard(self):
        self.assertEqual(1, len(self.agent._messaging.get_bindings('lobby')))

        self.agent.leave_shard('lobby')
        self.assertEqual(0, len(self.agent._messaging.get_bindings('lobby')))

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

    def tesGetingRequestWithoutInterest(self):
        '''Current implementation just ignores such events. Update this test
        in case we decide to do sth else'''
        key = (self.agent.get_descriptor()).doc_id
        msg = message.RequestMessage()
        msg.session_id = str(uuid.uuid1())
        return self.recv_msg(msg, self.endpoint, key)

    @defer.inlineCallbacks
    def testTerminatingTheAgent(self):
        # make him have running retrying request (covers all the hard cases)
        d = self.cb_after(None, self.agent, 'initiate_protocol')
        self.agent.retrying_protocol(DummyRequester, self.endpoint,
                                     args=(None, ))
        yield d

        self.assertEqual(1, len(self.agent._listeners))
        yield self.agent.terminate()

        self.assertCalled(self.agent.agent, 'shutdown')
        self.assertCalled(self.agent.agent, 'unregister')

        doc_id = self.agent._descriptor.doc_id
        d = self.agency._database.openDoc(doc_id)
        self.assertFailure(d, NotFoundError)
        yield d
        self.assertEqual(0, len(self.agency._agents))


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
        self.requester =\
            self.agent.initiate_protocol(DummyRequester,
                                         self.endpoint, payload)
        self.medium = self.requester._get_medium()
        self.finished = self.requester.notify_finish()
        self.assertIsInstance(self.finished, defer.Deferred)

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
                                 self.medium.state)
            return session_id, message

        d.addCallback(assertsOnMessage)

        def assertsOnAgency((session_id, msg, )):
            self.log('%r', self.agent._listeners.keys())
            self.assertTrue(session_id in self.agent._listeners.keys())
            listener = self.agent._listeners[session_id]
            self.assertEqual('AgencyRequester', listener.__class__.__name__)
            return session_id, msg

        d.addCallback(assertsOnAgency)

        def mimicReceivingResponse((session_id, msg, )):
            response = message.ResponseMessage()
            self.reply(response, self.endpoint, msg)

            return session_id

        d.addCallback(mimicReceivingResponse)
        d.addCallback(lambda _: self.finished)

        def assertGotResponseAndTerminated(session_id):
            self.assertFalse(session_id in self.agent._listeners.keys())
            self.assertTrue(self.requester.got_response)

        d.addCallback(assertGotResponseAndTerminated)

        return d

    @defer.inlineCallbacks
    def testRequestTimeout(self):
        delay.time_scale = 0.01

        d = self.queue.get()
        payload = 5
        self.requester =\
            yield self.agent.initiate_protocol(DummyRequester,
                                         self.endpoint, payload)
        self.medium = self.requester._get_medium()
        self.finished = self.requester.notify_finish()
        self.assertFailure(self.finished, protocols.InitiatorFailed)

        d.addCallback(self.cb_after, obj=self.agent,
                      method='unregister_listener')

        def assertTerminatedWithNoResponse(_):
            session_id = self.medium.session_id
            self.assertFalse(session_id in self.agent._listeners.keys())
            self.assertFalse(self.requester.got_response())
            self.assertEqual(requests.RequestState.closed,
                             self.medium.state)

        d.addCallback(assertTerminatedWithNoResponse)
        d.addCallback(lambda _: self.finished)

        yield d

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
                          obj=requester._get_medium(), method='_terminate')

        self.assertTrue(requester.got_response)
        self.assertEqual(0, len(sender._listeners))

        self.assertEqual(0, len(receiver._listeners))
        self.assertEqual(1, receiver.agent.got_payload)

    def _build_req_msg(self, recp):
        r = message.RequestMessage()
        r.session_id = str(uuid.uuid1())
        r.payload = 10
        return r


class DummyMedium(common.Mock, log.Logger, log.LogProxy):

    def __init__(self, testcase, success_at_try=None):
        log.Logger.__init__(self, testcase)
        log.LogProxy.__init__(self, testcase)

        self.number_called = 0
        self.success_at_try = success_at_try

    def initiate_protocol(self, factory, *args, **kwargs):
        self.number_called += 1
        self.info('called %d time', self.number_called)
        if self.success_at_try is not None and\
            self.success_at_try < self.number_called:
            return factory(True)
        else:
            return factory(False)


class DummyInitiator(common.Mock):

    def __init__(self, should_work):
        self.should_work = should_work

    def notify_finish(self):
        if self.should_work:
            return defer.succeed(None)
        else:
            return defer.fail(RuntimeError())


class TestRetryingProtocol(common.TestCase):

    timeout = 3

    def setUp(self):
        self.medium = DummyMedium(self)
        delay.time_scale = 0.01

    @defer.inlineCallbacks
    def testRetriesForever(self):
        d = self.cb_after(None, self.medium, 'initiate_protocol')
        instance = self._start_instance(None, 1, None)
        yield d
        yield self.cb_after(None, self.medium, 'initiate_protocol')
        yield self.cb_after(None, self.medium, 'initiate_protocol')
        yield self.cb_after(None, self.medium, 'initiate_protocol')
        yield self.cb_after(None, self.medium, 'initiate_protocol')
        instance.give_up()
        self.assertEqual(5, self.medium.number_called)

    @defer.inlineCallbacks
    def testMaximumNumberOfRetries(self):
        instance = self._start_instance(3, 1, None)
        d = instance.notify_finish()
        self.assertFailure(d, RuntimeError)
        yield d
        self.assertEqual(4, self.medium.number_called)
        self.assertEqual(8, instance.delay)

    @defer.inlineCallbacks
    def testMaximumDelay(self):
        instance = self._start_instance(3, 1, 2)
        d = instance.notify_finish()
        self.assertFailure(d, RuntimeError)
        yield d
        self.assertEqual(4, self.medium.number_called)
        self.assertEqual(2, instance.delay)

    def _start_instance(self, max_retries, initial_delay, max_delay):
        return agency.RetryingProtocol(
            self.medium, DummyInitiator, None, tuple(), dict(),
            max_retries, initial_delay, max_delay)
