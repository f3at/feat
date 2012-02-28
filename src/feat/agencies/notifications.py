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
# -*- Mode: Python -*-
# vi:si:et:sw=4:sts=4:ts=4
import uuid

from twisted.python import components
from zope.interface import implements

from feat.common import log, defer, error_handler, adapter
from feat.agencies import common, protocols
from feat.agents.base import replay

from interface import (IAgencyProtocolInternal, IAgencyInitiatorFactory,
                       IAgencyInterestInternalFactory)
from feat.interface.serialization import ISerializable
from feat.interface.collector import IAgencyCollector, ICollectorFactory
from feat.interface.poster import IAgencyPoster, IPosterFactory


class AgencyPoster(log.LogProxy, log.Logger, common.InitiatorMediumBase):

    implements(IAgencyPoster, ISerializable)

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


@adapter.register(IPosterFactory, IAgencyInitiatorFactory)
class AgencyPosterFactory(protocols.BaseInitiatorFactory):
    type_name = "poster-medium-factory"
    protocol_factory = AgencyPoster


class AgencyCollector(log.LogProxy, log.Logger, common.InterestedMediumBase):

    implements(IAgencyCollector, ISerializable, IAgencyProtocolInternal)

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
        self.guid = str(uuid.uuid1())

    def initiate(self):
        self.agent.journal_protocol_created(self.factory, self,
                                            *self.args, **self.kwargs)
        collector = self.factory(self.agent.get_agent(), self)
        self.collector = collector
        self.agent.register_protocol(self)

        self.agent.call_next(self._call, self.collector.initiate,
                             *self.args, **self.kwargs)

        return collector

    def on_message(self, message):
        return self._call(self.collector.notified, message)

    ### IAgencyCollector Methods ###

    ### IAgencyProtocolInternal Methods ###

    def cleanup(self):
        self.agent.unregister_protocol(self)
        return defer.succeed(None)

    def get_agent_side(self):
        return self.collector

    def is_idle(self):
        return self

    def notify_finish(self):
        return defer.succeed(None)

    ### ISerializable Methods ###

    def snapshot(self):
        return id(self)

    ### Private Methods ###

    def _call(self, method, *args, **kwargs):
        '''Call the method, wrap it in Deferred and bind error handler'''
        d = defer.maybeDeferred(method, *args, **kwargs)
        d.addErrback(lambda f: error_handler(self, f))
        return d


@adapter.register(ICollectorFactory, IAgencyInterestInternalFactory)
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

    ### Overriden IAgencyInterestInternal Methods ###

    def revoke(self):
        self.agency_collector.cleanup()
        protocols.BaseInterest.revoke(self)

    ### Overridden Protected Methods ###

    def _process_message(self, message):
        protocols.BaseInterest._process_message(self, message)
        self.agency_agent.call_next(self._pass_message, message)

    ### Private Methods ###

    def _pass_message(self, message):
        d = self.agency_collector.on_message(message)
        d.addBoth(defer.drop_param, self._message_processed, message)
