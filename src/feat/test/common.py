import functools
import uuid
import time

from twisted.internet import defer, reactor
from twisted.trial import unittest

from feat.agencies.emu import agency
from feat.agents import message, recipient
from feat.common import log

from . import factories

log.FluLogKeeper.init('test.log')


class TestCase(unittest.TestCase, log.FluLogKeeper, log.Logger):

    log_category = "test"

    def __init__(self, *args, **kwargs):
        unittest.TestCase.__init__(self, *args, **kwargs)
        log.FluLogKeeper.__init__(self)
        log.Logger.__init__(self, self)

    def cb_after(self, arg, obj, method):
        '''
        Returns defered fired after the call of method on object.
        Can be used in defered chain like this:

        d.addCallback(doSomeStuff)
        d.addCallback(self._cb_after, obj=something, method=some_method)
        d.addCallback(jobAfterCallOfSomeMethod)

        This will fire last callback after something.some_method has been
        called.
        Parameter passed to the last callback is either return value of
        doSomeStuff, or, if this is None, the return value of stubbed method.
        '''
        old_method = obj.__getattribute__(method)
        d = defer.Deferred()

        def new_method(*args, **kwargs):
            obj.__setattr__(method, old_method)
            ret = old_method(*args, **kwargs)
            reactor.callLater(0, d.callback, arg or ret)
            return ret

        obj.__setattr__(method, new_method)

        return d

    def assertCalled(self, obj, name, times=1, params=None):
        assert isinstance(obj, Mock), "Got: %r" % obj
        calls = obj.find_calls(name)
        times_called = len(calls)
        template = "Expected %s method to be called %d time(s), "\
                   "was called %d time(s)"
        self.assertEqual(times, times_called,\
                             template % (name, times, times_called))
        if params:
            for call in calls:
                self.assertEqual(len(params), len(call.args))
                for param, arg in zip(params, call.args):
                    self.assertTrue(isinstance(arg, param))

        return obj

    def assertIsInstance(self, _, klass):
        self.assertTrue(isinstance(_, klass),
             "Expected instance of %r, got %r instead" % (klass, _.__class__))
        return _

    def stub_method(self, obj, method, handler):
        handler = functools.partial(handler, obj)
        obj.__setattr__(method, handler)
        return obj


class Mock(object):

    def __init__(self):
        self._called = []

    def find_calls(self, name):
        return filter(lambda x: x.name == name, self._called)

    @staticmethod
    def stub(method):

        def decorated(self, *args, **kwargs):
            call = MockCall(method.__name__, args, kwargs)
            self._called.append(call)

        return decorated


class MockCall(object):

    def __init__(self, name, args, kwargs):
        self.name = name
        self.args = args
        self.kwargs = kwargs


class AgencyTestHelper(object):

    protocol_type = None
    protocol_id = None

    def setUp(self):
        self.agency = agency.Agency()
        self.session_id = None

    def _setup_endpoint(self):
        '''
        Sets up the destination for tested component to send messages to.

        @returns endpoint: Receipient instance pointing to the queue above
                           (use it for reply-to fields)
        @returns queue: Queue instance we use may .consume() on to get
                        messages from components being tested
        '''
        endpoint = recipient.Agent(str(uuid.uuid1()), 'lobby')
        queue = self.agency._messaging.defineQueue(endpoint.key)
        exchange = self.agency._messaging.defineExchange(endpoint.shard)
        exchange.bind(endpoint.key, queue)
        return endpoint, queue

    # methods for handling documents

    def doc_factory(self, doc_class, **options):
        '''Builds document of selected class and saves it to the database

        @returns: Document with id and revision set
        @return_type: subclass of feat.agents.document.Document
        '''
        document = factories.build(doc_class, **options)
        return self.agency._database.connection.save_document(document)

    # methods for sending and receiving custom messages

    def _send_announce(self, manager):
        msg = message.Announcement()
        manager.medium.announce(msg)
        return manager

    def _send_bid(self, contractor, bid=1):
        msg = message.Bid()
        msg.bids = [bid]
        contractor.medium.bid(msg)
        return contractor

    def _send_refusal(self, contractor):
        msg = message.Refusal()
        contractor.medium.refuse(msg)
        return contractor

    def _send_final_report(self, contractor):
        msg = message.FinalReport()
        contractor.medium.finalize(msg)
        return contractor

    def _send_cancel(self, contractor, reason=""):
        msg = message.Cancellation()
        msg.reason = reason
        contractor.medium.cancel(msg)
        return contractor

    def _recv_announce(self, *_):
        msg = message.Announcement()
        msg.session_id = str(uuid.uuid1())
        self.session_id = msg.session_id
        return self._recv_msg(msg).addCallback(lambda ret: _)

    def _recv_grant(self, _, bid_index=0, update_report=None):
        msg = message.Grant()
        msg.bid_index = bid_index
        msg.update_report = update_report
        msg.session_id = self.session_id
        return self._recv_msg(msg).addCallback(lambda ret: _)

    def _recv_rejection(self, _):
        msg = message.Rejection()
        msg.session_id = self.session_id
        return self._recv_msg(msg).addCallback(lambda ret: _)

    def _recv_cancel(self, _, reason=""):
        msg = message.Cancellation()
        msg.reason = reason
        msg.session_id = self.session_id
        return self._recv_msg(msg).addCallback(lambda ret: _)

    def _recv_ack(self, _):
        msg = message.Acknowledgement()
        msg.session_id = self.session_id
        return self._recv_msg(msg).addCallback(lambda ret: _)

    def _recv_msg(self, msg, reply_to=None, key='dummy-contract',
                  expiration_time=None):
        d = self.cb_after(arg=None, obj=self.agent, method='on_message')

        msg.reply_to = reply_to or self.endpoint
        msg.expiration_time = expiration_time or (time.time() + 10)
        msg.protocol_type = self.protocol_type
        msg.protocol_id = self.protocol_id
        msg.message_id = str(uuid.uuid1())

        shard = self.agent.descriptor.shard
        self.agent._messaging.publish(key, shard, msg)
        return d

    def _reply(self, msg, reply_to, original_msg):
        d = self.cb_after(arg=None, obj=self.agent, method='on_message')

        dest = recipient.IRecipient(original_msg)

        msg.reply_to = recipient.IRecipient(reply_to)
        msg.message_id = str(uuid.uuid1())
        msg.protocol_id = original_msg.protocol_id
        msg.expiration_time = time.time() + 10
        msg.protocol_type = original_msg.protocol_type
        msg.session_id = original_msg.session_id

        self.agent._messaging.publish(dest.key, dest.shard, msg)
        return d
