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
from feat.test.integration import common
from feat.agents.base import agent, descriptor, replay
from feat.database import document
from feat.common import defer, text_helper, serialization
from feat.agents.application import feat


@feat.register_descriptor('document-agent')
class Descriptor(descriptor.Descriptor):
    pass


@serialization.register
class Doc(document.Document):

    type_name = 'test_doc'
    document.field("counter", 0)


@feat.register_agent('document-agent')
class Agent(agent.BaseAgent):

    @replay.mutable
    def initiate(self, state):
        state.changes = []
        doc = Doc(doc_id='some_doc')
        return self.save_document(doc)

    @replay.mutable
    def register(self, state):
        return self.register_change_listener('some_doc', self._callback)

    @replay.mutable
    def cancel(self, state):
        self.cancel_change_listener('some_doc')

    @replay.mutable
    def _callback(self, state, doc_id, rev, deleted, own_change):
        state.changes.append((doc_id, rev, deleted, own_change))

    @replay.immutable
    def get_changes(self, state):
        return state.changes

    @replay.immutable
    def len_changes(self, state, num):

        def check():
            return len(state.changes) == num

        return check

    @replay.journaled
    def do_change(self, state):

        def increase_counter(doc):
            doc.counter += 1
            return doc

        f = self.get_document('some_doc')
        f.add_callback(increase_counter)
        f.add_callback(self.save_document)
        return f


@common.attr(timescale=0.05)
class TestNotifier(common.SimulationTest):

    timeout = 3

    @defer.inlineCallbacks
    def prolog(self):
        setup = text_helper.format_block("""
        agency = spawn_agency()
        agency.disable_protocol('setup-monitoring', 'Task')
        agency.start_agent(descriptor_factory('document-agent'), \
                           run_startup=False)
        """)
        yield self.process(setup)
        self.agent = self.get_local('_').get_agent()

    @defer.inlineCallbacks
    def testReceivingNotifications(self):
        yield self.agent.register()

        yield self.agent.do_change()

        yield self.wait_for(self.agent.len_changes(1), 1, 0.02)
        self.assert_last_change(deleted=False, own=True)

        doc = yield self.driver.get_document('some_doc')
        doc.counter = 5
        doc = yield self.driver.save_document(doc)

        yield self.wait_for(self.agent.len_changes(2), 1, 0.02)

        self.assert_last_change(deleted=False, own=False)

        yield self.agent.cancel()

        yield self.driver.delete_document(doc)
        yield common.delay(None, 0.1)
        self.assertEqual(2, len(self.agent.get_changes()))

        yield self.agent.register()

    def assert_last_change(self, deleted, own):
        doc_id, rev, deleted_, own_ = self.agent.get_changes()[-1]
        self.assertEqual(deleted, deleted_)
        self.assertEqual(own, own_)
