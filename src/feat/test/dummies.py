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
from zope.interface import implements

from feat.common import defer, time, log, journal, fiber, adapter, first
from feat.agents.base import descriptor, requester, replier, replay
from feat.agencies import protocols, common, message
from feat.agencies.net import config
from feat.database import emu as database

from feat.agencies.interface import IAgencyInterestInternalFactory
from feat.interface.protocols import IInterest, InterestType
from feat.interface.agent import IAgencyAgent, AgencyAgentState
from feat.interface.agency import ExecMode


class DummyBase(journal.DummyRecorderNode, log.LogProxy, log.Logger):

    def __init__(self, logger, now=None):
        journal.DummyRecorderNode.__init__(self)
        log.LogProxy.__init__(self, logger)
        log.Logger.__init__(self, logger)

        self.calls = {}
        self.now = now or time.time()
        self.call = None

    def do_calls(self):
        calls = self.calls.values()
        self.calls.clear()
        for _time, fun, args, kwargs in calls:
            fun(*args, **kwargs)

    def reset(self):
        self.calls.clear()

    def get_time(self):
        return self.now

    def call_next(self, call, *args, **kwargs):
        time.call_later(0, fiber.maybe_fiber, call, *args, **kwargs)

    def call_later(self, time, fun, *args, **kwargs):
        payload = (time, fun, args, kwargs)
        callid = id(payload)
        self.calls[callid] = payload
        return callid

    def call_later_ex(self, time, fun, args=(), kwargs={}, busy=True):
        payload = (time, fun, args, kwargs)
        callid = id(payload)
        self.calls[callid] = payload
        return callid

    def cancel_delayed_call(self, callid):
        if callid in self.calls:
            del self.calls[callid]


class ListOfProtocols(list):

    def by_factory(self, factory):
        return (x for x in self if x.factory == factory)

    def wait_for(self, factory, timeout=10):

        def get_first(factory):
            return first(self.by_factory(factory))

        d = time.wait_for(get_first, timeout, factory)
        d.addCallback(defer.drop_result, get_first, factory)
        return d


class DummyAgent(DummyBase):

    descriptor_class = descriptor.Descriptor

    def __init__(self, logger, db=None):
        DummyBase.__init__(self, logger)
        self.descriptor = self.descriptor_class(shard='test_shard')
        self.protocols = ListOfProtocols()

        # db connection
        self._db = db and db or database.Database().get_connection()
        self._db.save_document(self.descriptor)

        self.notifications = list()

        # call_id -> DelayedCall
        self._delayed_calls = dict()

    def reset(self):
        del self.protocols[:]
        DummyBase.reset(self)

    def get_database(self):
        return self._db

    def initiate_protocol(self, factory, *args, **kwargs):
        instance = DummyProtocol(factory, args, kwargs)
        self.protocols.append(instance)
        return instance

    def get_descriptor(self):
        return self.descriptor

    def update_descriptor(self, _method, *args, **kwargs):
        f = fiber.succeed()
        f.add_callback(fiber.drop_param,
                      _method, self.descriptor, *args, **kwargs)
        return f

    def register_change_listener(self, doc_id, cb, **kwargs):
        if isinstance(doc_id, (str, unicode)):
            doc_id = (doc_id, )
        self._db.changes_listener(doc_id, cb, **kwargs)

    def cancel_change_listener(self, doc_id):
        self._db.cancel_listener(doc_id)

    def get_document(self, doc_id):
        return fiber.wrap_defer(self._db.get_document, doc_id)

    def save_document(self, document):
        return fiber.wrap_defer(self._db.save_document, document)

    def update_document(self, doc_or_id, *args, **kwargs):
        return fiber.wrap_defer(self._db.update_document, doc_or_id,
                                *args, **kwargs)

    def delete_document(self, document):
        return fiber.wrap_defer(self._db.delete_document, document)

    def query_view(self, factory, **kwargs):
        return fiber.wrap_defer(self._db.query_view, factory, **kwargs)

    def get_attachment_body(self, attachment):
        return fiber.wrap_defer(self._database.get_attachment, attachment)

    ### IDocumentChangeListner ###

    def on_document_change(self, doc):
        self.notifications.append(('change', doc.doc_id, doc))

    def on_document_deleted(self, doc_id):
        self.notifications.append(('delete', doc_id, None))


class DummyMediumBase(DummyAgent):

    implements(IAgencyAgent)

    def register_interest(self, interest):
        return DummyInterest()

    def get_ip(self):
        return '127.0.0.1'

    def bid(self, message):
        pass

    def finalize(self):
        pass

    def get_mode(self, compoment):
        return ExecMode.test

    def get_configuration(self):
        raise NotImplementedError()


class DummyAgency(object):

    def get_config(self):
        return config.Config(db=config.DbConfig(name=u'test'))


class DummyMedium(DummyMediumBase):

    agency = DummyAgency()
    state = AgencyAgentState.ready

    def leave_shard(self, shard):
        pass

    def join_shard(self, shard):
        pass

    def get_own_address(self):
        return self.get_ip()

    def observe(self, _method, *args, **kwargs):
        res = common.Observer(_method, *args, **kwargs)
        self.call_next(res.initiate)
        return res

    def get_hostname(self):
        return 'test.feat.lan'

    # FIXME: methods below are overriden because of messed up dummy class
    # inheritance. This class inherits from DummyAgents which would return
    # fibers instead of deferreds.

    def get_document(self, doc_id):
        return self._db.get_document(doc_id)

    def get_attachment_body(self, attachment):
        return self._database.get_attachment(attachment)

    def save_document(self, document):
        return self._db.save_document(document)

    def update_document(self, doc_or_id, *args, **kwargs):
        return self._db.update_document(doc_or_id, *args, **kwargs)

    def delete_document(self, document):
        return self._db.delete_document(document)

    def query_view(self, factory, **kwargs):
        return self._db.query_view(factory, **kwargs)

    ### endof FIXME ###


class DummyProtocol(object):

    def __init__(self, factory, args, kwargs):
        self.factory = factory
        self.args = args
        self.kwargs = kwargs
        self.deferred = defer.Deferred()

    def notify_finish(self):
        return fiber.wrap_defer(self.get_def)

    def get_def(self):
        return self.deferred

    def execute(self, agent):
        instance = self.factory(agent,
                                DummyProtocolMedium(agent, self.factory))
        d = instance.initiate(*self.args, **self.kwargs)
        d.chainDeferred(self.deferred)
        return self.deferred

    ### used if it's a Poster ###

    def notify(self, *args, **kwargs):
        pass

    def finalize(self):
        pass


class DummyProtocolMedium(DummyMedium):

    def __init__(self, agent, factory):
        DummyMedium.__init__(self, agent)
        self._agent = agent
        self._expiration_time = agent.get_time() + factory.timeout

    def get_expiration_time(self):
        return self._expiration_time


@adapter.register(IInterest, IAgencyInterestInternalFactory)
class DummyAgencyInterest(protocols.DialogInterest):
    pass


class DummyInterest(object):

    implements(IInterest)

    def __init__(self):
        self.protocol_type = "Contract"
        self.protocol_id = "some-contract"
        self.interest_type = InterestType.public
        self.initiator = message.Announcement

    def bind_to_lobby(self):
        pass


class DummyRequester(requester.BaseRequester):

    protocol_id = 'dummy-request'
    timeout = 2

    @replay.entry_point
    def initiate(self, state, argument):
        state._got_response = False
        msg = message.RequestMessage()
        msg.payload = argument
        state.medium.request(msg)

    @replay.entry_point
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

    @replay.entry_point
    def requested(self, state, request):
        state.agent.got_payload = request.payload
        state.medium.reply(message.ResponseMessage())


class DummyPosterMedium(DummyMediumBase):

    def __init__(self):
        self.messages = list()

    def post(self, msg):
        self.messages.append(msg)


class DummyContractorMedium(
    journal.DummyRecorderNode, log.LogProxy, log.Logger):

    def __init__(self):
        journal.DummyRecorderNode.__init__(self)
        log.LogProxy.__init__(self, log.get_default())
        log.Logger.__init__(self, self)
        self.bid_sent = None
        self.handover_sent = None
        self.refusal_sent = None
        self.defect_sent = None
        self.report_sent = None
        self.updated_address = None

    def bid(self, bid):
        self.bid_sent = bid

    def handover(self, bid):
        self.handover_sent = bid

    def refuse(self, refusal):
        self.refusal_sent = refusal

    def defect(self, cancellation):
        self.defect_sent = cancellation

    def finalize(self, report):
        self.report_sent = report

    def update_manager_address(self, recipient):
        self.updated_address = recipient
