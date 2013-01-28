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
from twisted.internet import defer

from feat.common.text_helper import format_block
from feat.test.integration import common
from feat.agents.base import (agent, descriptor,
                              partners, replay, resource, requester, )
from feat.agencies import recipient
from feat.common import serialization, fiber
from feat.agents.application import feat


class FailureOfPartner(Exception):
    pass


@feat.register_descriptor('partner-agent')
class Descriptor(descriptor.Descriptor):
    pass


@serialization.register
class FailingPartner(partners.BasePartner):

    def initiate(self, agent):
        return fiber.fail(FailureOfPartner('test'))


@serialization.register
class GettingInfoPartner(partners.BasePartner):

    def on_goodbye(self, agent, brothers):
        agent.notify_brothers(brothers)


@serialization.register
class ExtraParamsPartner(partners.BasePartner):

    def initiate(self, agent, extra_param):
        self.param = extra_param


@serialization.register
class ResponsablePartner(partners.BasePartner):

    def on_died(self, agent, brothers, monitor):
        assert recipient.IRecipient.providedBy(monitor)
        return 'ACCEPT_RESPONSABILITY'

    def on_restarted(self, agent, old_recipient):
        assert old_recipient
        assert self.recipient.route == 'shard'
        agent.done_migrated()

    def on_buried(self, agent, brothers):
        pass


class Partners(agent.Partners):

    default_role = 'default_role'

    partners.has_many('failers', 'partner-agent', FailingPartner, 'failer')
    partners.has_many('info', 'partner-agent', GettingInfoPartner, 'info')
    partners.has_many('caretaker', 'partner-agent', ResponsablePartner,
                      'caretaker')
    partners.has_many('param', 'partner-agent', ExtraParamsPartner, 'param')


@feat.register_agent('partner-agent')
class Agent(agent.BaseAgent, resource.AgentMixin):

    partners_class = Partners

    @replay.mutable
    def initiate(self, state):
        state.resources.define('foo', resource.Scalar, 2)
        state.received_brothers = list()
        state.migrated = False

    @replay.mutable
    def done_migrated(self, state):
        state.migrated = True

    @replay.immutable
    def has_migrated(self, state):
        return state.migrated

    @replay.mutable
    def notify_brothers(self, state, brothers):
        state.received_brothers.append(brothers)

    @replay.immutable
    def get_received_brothers(self, state):
        return state.received_brothers

    @replay.journaled
    def notify_died(self, state, recp, origin):
        return requester.notify_died(self, recp, origin, 'payload')

    @replay.journaled
    def notify_buried(self, state, recp, origin):
        return requester.notify_buried(self, recp, origin, 'payload')

    @replay.journaled
    def notify_restarted(self, state, recp, origin, new_address):
        return requester.notify_restarted(self, recp, origin, new_address)


@common.attr(timescale=0.05)
class PartnershipTest(common.SimulationTest):

    @defer.inlineCallbacks
    def prolog(self):
        # for this tests override DummyAgent with BaseAgent

        setup = format_block("""
        agency = spawn_agency(start_host=False)
        initiator = agency.start_agent(descriptor_factory('partner-agent'))
        receiver = agency.start_agent(descriptor_factory('partner-agent'))
        """)
        yield self.process(setup)
        self.receiver = self.get_local('receiver')
        self.initiator = self.get_local('initiator')
        self.agency = self.get_local('agency')

    def testValidateProlog(self):
        self.assertEqual(2, len(self.agency._agents))
        self.assertIsInstance(self.agency._agents[0].agent, agent.BaseAgent)
        self.assertIsInstance(self.agency._agents[1].agent, agent.BaseAgent)

    @defer.inlineCallbacks
    def testEstablishPartnership(self):
        yield self._establish_partnership()

        i_partners = self.initiator.get_descriptor().partners
        self.assertEqual(1, len(i_partners))
        self.assertEqual('default_role', i_partners[0].role)
        r_partners = self.receiver.get_descriptor().partners
        self.assertEqual(1, len(r_partners))
        self.assertEqual('default_role', r_partners[0].role)

    @defer.inlineCallbacks
    def testInitiatorTerminates(self):
        yield self._establish_partnership()

        yield self.initiator._terminate()
        yield self.wait_for_idle(5)

        self.assertEqual(1, len(self.agency._agents))
        self.assertEqual(0, len(self.receiver.get_descriptor().partners))

    @defer.inlineCallbacks
    def testReceiverTerminates(self):
        yield self._establish_partnership()

        yield self.receiver._terminate()
        yield self.wait_for_idle(5)

        self.assertEqual(1, len(self.agency._agents))
        self.assertEqual(0, len(self.initiator.get_descriptor().partners))

    @defer.inlineCallbacks
    def testThreeAgents(self):
        '''
        Three agents, all being partners. Than check the termination of
        two of them.
        '''
        yield self.process(format_block("""
        third = agency.start_agent(descriptor_factory('partner-agent'))
        """))

        agents = [self.initiator, self.receiver, self.get_local('third')]

        yield self._establish_partnership('initiator', 'receiver')
        self.assert_partners(agents, [1, 1, 0])
        yield self._establish_partnership('receiver', 'third')
        self.assert_partners(agents, [1, 2, 1])
        yield self._establish_partnership('third', 'initiator')
        self.assert_partners(agents, [2, 2, 2])

        yield self.initiator._terminate()
        yield self.wait_for_idle(5)

        self.assert_partners(agents, [2, 1, 1])

        yield self.receiver._terminate()
        yield self.wait_for_idle(5)
        self.assert_partners(agents, [2, 1, 0])

    @defer.inlineCallbacks
    def testGetingInfo(self):
        yield self.process(format_block("""
        third = agency.start_agent(descriptor_factory('partner-agent'))
        """))

        agents = [self.initiator, self.receiver, self.get_local('third')]

        yield self._partnership_with_info(agents[0], agents[1])
        yield self._partnership_with_info(agents[2], agents[1])
        yield self._partnership_with_info(agents[2], agents[0])
        yield self.initiator._terminate()

        recv = self.receiver.get_agent().get_received_brothers()
        self.assertEqual(1, len(recv))
        self.assertEqual(2, len(recv[0]))
        for x in recv[0]:
            self.assertIsInstance(x, GettingInfoPartner)

    @defer.inlineCallbacks
    def testSubstitutePartner(self):
        '''
        Three agents, all being partners. Than check the termination of
        two of them.
        '''
        yield self.process(format_block("""
        third = agency.start_agent(descriptor_factory('partner-agent'))
        """))

        agents = [self.initiator, self.receiver, self.get_local('third')]

        alloc1 = yield agents[2].get_agent().allocate_resource(foo=1)
        alloc2 = yield agents[2].get_agent().allocate_resource(foo=1)

        yield self._establish_partnership('initiator', 'receiver')
        self.assert_partners(agents, [1, 1, 0])
        yield self.initiator.get_agent().substitute_partner(
            recipient.IRecipient(self.receiver),
            recipient.IRecipient(agents[2]),
            alloc1.id)
        self.assert_partners(agents, [1, 1, 1])
        yield self.receiver.get_agent().substitute_partner(
            recipient.IRecipient(self.initiator),
            recipient.IRecipient(agents[2]),
            alloc2.id)
        self.assert_partners(agents, [1, 1, 2])

    @defer.inlineCallbacks
    def testFailingPartner(self):
        d = self._failing_partnership(self.initiator, self.receiver)
        self.assertFailure(d, FailureOfPartner)
        yield d
        agents = [self.initiator, self.receiver]
        self.assert_partners(agents, [0, 0, 0])

    @defer.inlineCallbacks
    def testEstablishPartnershipWithAllocations(self):
        i_alloc = yield self.initiator.get_agent().allocate_resource(foo=1)
        r_alloc = yield self.receiver.get_agent().allocate_resource(foo=1)
        yield self.initiator.get_agent().establish_partnership(
            recipient.IRecipient(self.receiver), i_alloc.id, r_alloc.id)

        agents = [self.initiator, self.receiver]
        self.assert_partners(agents, [1, 1])
        for medium in agents:
            agent = medium.get_agent()
            partner = agent.query_partners('all')[0]
            self.assertTrue(partner.allocation_id is not None)

    @common.attr(timescale=0.1)
    @defer.inlineCallbacks
    def testEstablishPartnershipWithPreAllocaton(self):
        i_alloc = yield self.initiator.get_agent().allocate_resource(foo=1)
        r_alloc = yield self.receiver.get_agent().preallocate_resource(foo=1)
        d = self.initiator.get_agent().establish_partnership(
            recipient.IRecipient(self.receiver), i_alloc.id, r_alloc.id)
        self.assertFailure(d, resource.AllocationNotFound)
        yield d

        agents = [self.initiator, self.receiver]
        self.assert_partners(agents, [0, 0])
        r_alloc = yield self.receiver.get_agent().release_resource(r_alloc.id)

    @common.attr(timescale=0.1)
    @defer.inlineCallbacks
    def testEstablishPartnershipWithUnknownAllocaton(self):
        i_alloc = yield self.initiator.get_agent().allocate_resource(foo=1)
        d = self.initiator.get_agent().establish_partnership(
            recipient.IRecipient(self.receiver), i_alloc.id, 2)
        self.assertFailure(d, resource.AllocationNotFound)
        yield d

        agents = [self.initiator, self.receiver]
        self.assert_partners(agents, [0, 0])

    @defer.inlineCallbacks
    def testNotifyKilledRestarted(self):
        yield self._partnership_taking_care(self.initiator, self.receiver)
        partner_obj = self.receiver.get_agent().query_partners('caretaker')[0]
        self.assertIsInstance(partner_obj, ResponsablePartner)

        irecv = recipient.IRecipient(self.receiver)
        iinit = recipient.IRecipient(self.initiator)

        monitor = yield self._start_agent()
        resp = yield monitor.notify_died(irecv, iinit)
        self.assertEqual('ACCEPT_RESPONSABILITY', resp)

        new_address = recipient.Agent(agent_id = iinit.key, route=u'shard')
        yield monitor.notify_restarted(irecv, iinit, new_address)
        yield self.wait_for_idle(3)
        self.assertTrue(self.receiver.get_agent().has_migrated())

        partner_obj = self.receiver.get_agent().query_partners('caretaker')[0]
        self.assertEqual(new_address, partner_obj.recipient)

    @defer.inlineCallbacks
    def testNotifyburied(self):
        yield self._partnership_taking_care(self.initiator, self.receiver)
        irecv = recipient.IRecipient(self.receiver)
        iinit = recipient.IRecipient(self.initiator)

        monitor = yield self._start_agent()

        yield monitor.notify_buried(irecv, iinit)
        yield self.wait_for_idle(3)

        partner_obj = self.receiver.get_agent().query_partners('caretaker')
        self.assertEqual(0, len(partner_obj))

    @defer.inlineCallbacks
    def testPassingExtraParam(self):
        yield self._partnership_parametrized(self.initiator, self.receiver,
                                             extra_param='something',
                                             bad_name_param='baaad')
        par = self.initiator.get_agent().query_partners('param')
        self.assertEqual(1, len(par))
        self.assertEqual('something', par[0].param)
        par = self.receiver.get_agent().query_partners('param')
        self.assertEqual(1, len(par))
        self.assertEqual('something', par[0].param)

    def assert_partners(self, agents, expected):
        for agent, e in zip(agents, expected):
            self.assertEqual(e, len(agent.get_descriptor().partners))

    def _establish_partnership(self, initiator='initiator',
                               receiver='receiver'):
        script = format_block("""
        agent = %s.get_agent()
        agent.propose_to(%s)
        """ % (initiator, receiver, ))
        return self.process(script)

    def _failing_partnership(self, initiator, receiver):
        return self._partnership(initiator, receiver, None, 'failer')

    def _partnership_with_info(self, initiator, receiver):
        return self._partnership(initiator, receiver, 'info', 'info')

    def _partnership_taking_care(self, initiator, receiver):
        return self._partnership(initiator, receiver, 'caretaker', 'caretaker')

    def _partnership_parametrized(self, initiator, receiver, **options):
        return initiator.get_agent().establish_partnership(
            recipient.IRecipient(receiver), partner_role='param',
            our_role='param', **options)

    def _partnership(self, initiator, receiver,
                     partner_role=None, our_role=None):
        return initiator.get_agent().propose_to(
            recipient.IRecipient(receiver), partner_role=partner_role,
            our_role=our_role)

    @defer.inlineCallbacks
    def _start_agent(self):
        yield self.process(format_block("""
        agency.start_agent(descriptor_factory('partner-agent'))
        _.get_agent()
        """))

        defer.returnValue(self.get_local('_'))
