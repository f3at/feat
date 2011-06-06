# -*- Mode: Python -*-
# vi:si:et:sw=4:sts=4:ts=4
import uuid

from twisted.python import components
from zope.interface import implements

from feat.common import log, defer, error_handler
from feat.agencies import common, protocols
from feat.agents.base import replay

from interface import *
from feat.interface.serialization import *
from feat.interface.collector import *
from feat.interface.poster import *


class AgencyPoster(log.LogProxy, log.Logger, common.InitiatorMediumBase):

    implements(IAgencyPoster, ISerializable)

    log_category = "poster-medium"
    type_name = "poster-medium"

    def __init__(self, agency_agent, factory, recipients, *args, **kwargs):
        log.Logger.__init__(self, agency_agent)
        log.LogProxy.__init__(self, agency_agent)
        common.InitiatorMediumBase.__init__(self)

        self.agent = agency_agent
        self.factory = factory
        self.recipients = recipients
        self.args = args
        self.kwargs = kwargs
        self.protocol_id = None

    def initiate(self):
        self.agent.journal_protocol_created(self.factory, self,
                                            *self.args, **self.kwargs)
        poster = self.factory(self.agent.get_agent(), self)

        self.poster = poster
        self.log_name = poster.__class__.__name__
        self.protocol_id = poster.protocol_id

        self.agent.call_next(self._call, poster.initiate,
                             *self.args, **self.kwargs)

        return poster

    ### IAgencyPoster Methods ###

    @replay.named_side_effect('AgencyPoster.post')
    def post(self, msg, recipients=None, expiration_time=None):
        msg.protocol_id = self.protocol_id
        if msg.expiration_time is None:
            if expiration_time is None:
                now = self.agent.get_time()
                expiration_time = now + self.poster.notification_timeout
            msg.expiration_time = expiration_time
        if msg.traversal_id is None:
            msg.traversal_id = str(uuid.uuid1())

        if not recipients:
            recipients = self.recipients

        return self.agent.send_msg(recipients, msg)

    ### ISerializable Methods ###

    def snapshot(self):
        return id(self)

    ### Private Methods ###

    def _call(self, method, *args, **kwargs):
        '''Call the method, wrap it in Deferred and bind error handler'''
        d = defer.maybeDeferred(method, *args, **kwargs)
        d.addErrback(lambda f: error_handler(self, f))
        return d


class AgencyPosterFactory(protocols.BaseInitiatorFactory):
    type_name = "poster-medium-factory"
    protocol_factory = AgencyPoster


components.registerAdapter(AgencyPosterFactory,
                           IPosterFactory,
                           IAgencyInitiatorFactory)


class AgencyCollector(log.LogProxy, log.Logger, common.InterestedMediumBase):

    implements(IAgencyCollector, ISerializable)

    log_category = "collector-medium"
    type_name = "collector-medium"

    def __init__(self, agency_agent, factory, *args, **kwargs):
        log.Logger.__init__(self, agency_agent)
        log.LogProxy.__init__(self, agency_agent)
        common.InterestedMediumBase.__init__(self)

        self.agent = agency_agent
        self.factory = factory
        self.args = args
        self.kwargs = kwargs

        self.collector = None

    def initiate(self):
        self.agent.journal_protocol_created(self.factory, self,
                                            *self.args, **self.kwargs)
        collector = self.factory(self.agent.get_agent(), self)

        self.collector = collector
        self.log_name = collector.__class__.__name__

        self.agent.call_next(self._call, self.collector.initiate,
                             *self.args, **self.kwargs)

        return collector

    def on_message(self, message):
        return self._call(self.collector.notified, message)

    ### IAgencyCollector Methods ###


    ### ISerializable Methods ###

    def snapshot(self):
        return id(self)

    ### Private Methods ###

    def _call(self, method, *args, **kwargs):
        '''Call the method, wrap it in Deferred and bind error handler'''
        d = defer.maybeDeferred(method, *args, **kwargs)
        d.addErrback(lambda f: error_handler(self, f))
        return d


class AgencyCollectorInterest(protocols.BaseInterest):

    ### Overridden IAgencyInterestInternalFactory Methods ###

    def __call__(self, agency_agent, *args, **kwargs):
        protocols.BaseInterest.__call__(self, agency_agent)
        # We create the agent-side factory right away
        self.debug('Instantiating collector protocol')

        medium = AgencyCollector(self.agency_agent, self.agent_factory,
                                 *args, **kwargs)
        medium.initiate()

        self.agency_collector = medium

        return self

    ### Overridden Protected Methods ###

    def _process_message(self, message):
        protocols.BaseInterest._process_message(self, message)
        self.agency_agent.call_next(self._pass_message, message)

    ### Private Methods ###

    def _pass_message(self, message):
        d = self.agency_collector.on_message(message)
        d.addBoth(defer.drop_param, self._message_processed, message)


components.registerAdapter(AgencyCollectorInterest,
                           ICollectorFactory,
                           IAgencyInterestInternalFactory)
