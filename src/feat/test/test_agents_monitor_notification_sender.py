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

from feat.agents.monitor import monitor_agent
from feat.test import common
from feat.test.dummies import DummyMedium, DummyAgent
from feat.common import defer, fiber
from feat.agents.base import sender, descriptor
from feat.agencies import recipient

from feat.agents.monitor.interface import *
from feat.interface.protocols import *
from feat.database.interface import NotFoundError


class DummyMonitorAgent(DummyAgent):

    descriptor_class = monitor_agent.Descriptor

    def __init__(self, logger):
        DummyAgent.__init__(self, logger)
        self.docs = dict()

    def get_document(self, doc_id):
        if doc_id in self.docs:
            return fiber.succeed(self.docs[doc_id])
        else:
            return fiber.fail(NotFoundError())


class DummyClerk(dict):
    implements(IClerk)

    def has_patient(self, agent_id):
        return agent_id in self

    def get_patient(self, agent_id):
        status = self.get(agent_id, None)
        if status is not None:
            return Status(status)


class Status(object):
    implements(IPatientStatus)

    def __init__(self, status):
        self.state = status


class NotificationSenderTest(common.TestCase):

    @defer.inlineCallbacks
    def setUp(self):
        yield common.TestCase.setUp(self)
        self.medium = DummyMedium(self)
        self.agent = DummyMonitorAgent(self)
        self.clerk = DummyClerk()
        self.task = sender.NotificationSender(self.agent, self.medium)
        yield self.task.initiate(self.clerk)
        self.recp = recipient.Agent(agent_id='agent_id', route='shard')

    @defer.inlineCallbacks
    def testDryRunMethod(self):
        # dry run should not trigger anything
        yield self.task.run()
        self.assert_protocols(0)

    @defer.inlineCallbacks
    def testNonExistingAgnet(self):
        # check sending notification to nonexisting agent (no descriptor)
        n1 = self.gen_notification(recipient=self.recp)
        notification = self.gen_notification(recipient=self.recp)
        yield self.task.notify([n1, notification])
        self.assert_pending('agent_id', 2)

        d = self.task.run()
        self.assert_protocols(1)
        self.fail_protocol(0)
        yield d
        self.assert_pending('agent_id', 0)

    @defer.inlineCallbacks
    def testExistingAgent(self):
        # now tests same thing, but with descriptor existing
        self.agent.reset()
        notification = self.gen_notification(recipient=self.recp)
        self.gen_document(self.recp)

        yield self.task.notify([notification])
        self.assert_pending('agent_id', 1)
        d = self.task.run()
        self.assert_protocols(1)
        self.fail_protocol(0)
        yield d
        self.assert_pending('agent_id', 1)

    @defer.inlineCallbacks
    def testSuccessfulFlushing(self):
        n1 = self.gen_notification(recipient=self.recp)
        n2 = self.gen_notification(recipient=self.recp)
        self.task.notify([n1, n2])
        d = self.task.run()
        self.assert_pending('agent_id', 2)
        self.assert_protocols(1)
        self.succeed_protocol(0)
        self.assert_pending('agent_id', 1)
        self.assert_protocols(2)
        self.succeed_protocol(1)
        yield d
        self.assert_pending('agent_id', 0)

    @defer.inlineCallbacks
    def testIntegrationWithClerk(self):
        self.clerk['agent_id'] = PatientState.dead
        n1 = self.gen_notification(recipient=self.recp)
        n2 = self.gen_notification(recipient=self.recp)
        self.task.notify([n1, n2])
        d = self.task.run()
        self.assert_pending('agent_id', 2)
        self.assert_protocols(0)
        yield d

        self.clerk['agent_id'] = PatientState.alive
        d = self.task.run()
        self.assert_pending('agent_id', 2)
        self.assert_protocols(1)
        self.fail_protocol(0)
        yield d
        self.assert_pending('agent_id', 0)

    @defer.inlineCallbacks
    def testMigratingShard(self):
        n1 = self.gen_notification(recipient=self.recp)
        n2 = self.gen_notification(recipient=self.recp)
        self.task.notify([n1, n2])

        new_recp = recipient.Agent(self.recp.key, route=u'other shard')
        self.gen_document(new_recp)

        d = self.task.run()
        self.assert_pending('agent_id', 2)
        self.assert_protocols(1)
        self.fail_protocol(0)
        yield d

        self.assert_pending('agent_id', 2)
        for notif in self.agent.descriptor.pending_notifications['agent_id']:
            self.assertEqual('other shard', notif.recipient.route)

    def assert_pending(self, agent_id, num):
        if num == 0:
            self.assertFalse(agent_id in
                             self.agent.descriptor.pending_notifications)
        else:
            self.assertTrue(agent_id in
                            self.agent.descriptor.pending_notifications)
            self.assertEqual(
                num,
                len(self.agent.descriptor.pending_notifications[agent_id]))

    def gen_document(self, recp):
        self.agent.docs[recp.key] = descriptor.Descriptor(doc_id=recp.key,
                                                          shard=recp.route)

    def succeed_protocol(self, index):
        self.agent.protocols[index].deferred.callback(None)

    def fail_protocol(self, index):
        self.agent.protocols[index].deferred.errback(ProtocolFailed())

    def assert_protocols(self, num):
        self.assertEqual(num, len(self.agent.protocols))

    def gen_notification(self, **options):
        return sender.PendingNotification(**options)
