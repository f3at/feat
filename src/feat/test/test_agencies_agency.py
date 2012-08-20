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
from feat.common import defer, serialization
from feat.interface.agent import AgencyAgentState
from feat.agents.base import descriptor, agent
from feat.database import document
from feat.test import common
from feat.agents.application import feat


@feat.register_descriptor('startup-test')
class Descriptor(descriptor.Descriptor):
    pass


@serialization.register
class Config(document.Document):

    type_name = 'startup-test_conf'
    document.field('field', None)


class DummyException(Exception):
    pass


@feat.register_agent('startup-test')
class DummyAgent(agent.BaseAgent, common.Mock):

    need_local_monitoring = False

    def __init__(self, medium):
        agent.BaseAgent.__init__(self, medium)
        common.Mock.__init__(self)
        self._started_defer = defer.Deferred()

    @common.Mock.record
    def initiate(self, startup_fail=False):
        self.startup_fail = startup_fail

    @common.Mock.stub
    def shutdown(self):
        pass

    @common.Mock.record
    def startup(self):
        if self.startup_fail:
            raise DummyException('')
        return self._started_defer

    @common.Mock.stub
    def on_configuration_change(self, config):
        pass

    @common.Mock.stub
    def on_disconnect(self):
        pass

    @common.Mock.stub
    def on_reconnect(self):
        pass

    def set_started(self):
        self._started_defer.callback(self)

    def _wait_started(self, _):
        return self._started_defer


class TestAgentCallbacks(common.TestCase, common.AgencyTestHelper):

    @defer.inlineCallbacks
    def setUp(self):
        yield common.TestCase.setUp(self)
        yield common.AgencyTestHelper.setUp(self)
        self.desc = yield self.doc_factory(Descriptor)

    @defer.inlineCallbacks
    def testChangingConfiguration(self):
        db = self._db.get_connection()
        conf = Config(field=1, doc_id=u'startup-test_conf')
        conf = yield db.save_document(conf)
        medium = yield self.agency.start_agent(self.desc)
        agent = medium.get_agent()

        # test getting config
        conf_ = medium.get_configuration()
        self.assertEquals(conf, conf_)

        # modify it
        self.assertCalled(agent, 'on_configuration_change', times=0)
        conf.field = 3
        conf = yield db.save_document(conf)
        kwargs = dict(name='on_configuration_change')
        yield self.wait_for(agent.find_calls, 10, kwargs=kwargs)

        # assert that callback is called
        call = agent.find_calls('on_configuration_change')[0]
        conf_ = call.kwargs['config']
        self.assertIsInstance(conf_, Config)
        self.assertEqual(3, conf_.field)

        # check that synchrounous getter gives the new value
        conf_ = medium.get_configuration()
        self.assertEqual(conf, conf_)

    @defer.inlineCallbacks
    def testAgentStartup(self):
        medium = yield self.agency.start_agent(self.desc)
        agent = medium.get_agent()
        self.assertCalled(agent, 'initiate')
        self.assertCalled(agent, 'startup', times=0)
        self.assertEqual(medium.get_machine_state(),
                         AgencyAgentState.initiated)
        medium.get_agent().set_started()
        yield medium.wait_for_state(AgencyAgentState.ready)
        self.assertCalled(medium.get_agent(), 'startup', times=1)

    @defer.inlineCallbacks
    def testAgentNoStartup(self):
        medium = yield self.agency.start_agent(self.desc, run_startup=False)
        agent = medium.get_agent()
        yield medium.wait_for_state(AgencyAgentState.ready)
        self.assertCalled(agent, 'startup', times=0)
        self.assertEqual(medium.get_machine_state(), AgencyAgentState.ready)

    @defer.inlineCallbacks
    def testAgentFails(self):
        desc = yield self.doc_factory(Descriptor)
        medium = yield self.agency.start_agent(desc, startup_fail=True)
        yield medium.wait_for_state(AgencyAgentState.terminated)

    @defer.inlineCallbacks
    def testAgencyDisconnects(self):
        medium = yield self.agency.start_agent(self.desc)
        agent = medium.get_agent()
        agent.set_started()
        yield medium.wait_for_state(AgencyAgentState.ready)

        messaging = self.agency._messaging
        database = self.agency._database

        messaging._on_disconnected()
        yield medium.wait_for_state(AgencyAgentState.disconnected)

        yield common.delay(None, 0.01)
        self.assertCalled(agent, 'on_disconnect')

        messaging._on_connected()
        yield medium.wait_for_state(AgencyAgentState.ready)
        yield common.delay(None, 0.01)

        self.assertCalled(agent, 'on_disconnect')
        self.assertCalled(agent, 'on_reconnect')

        messaging._on_disconnected()
        database._on_disconnected()
        yield common.delay(None, 0.01)
        self.assertCalled(agent, 'on_disconnect', times=2)

        messaging._on_connected()
        yield common.delay(None, 0.01)
        self.assertCalled(agent, 'on_reconnect', times=1)

        database._on_connected()
        yield common.delay(None, 0.02)
        self.assertCalled(agent, 'on_reconnect', times=2)
