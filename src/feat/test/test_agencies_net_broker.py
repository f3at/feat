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
import uuid
import os

from twisted.internet import defer
from twisted.python import failure

from feat.test import common
from feat.agencies.net import broker
from feat.common import log, manhole, first


class DummyAgency(log.LogProxy, manhole.Manhole, log.Logger):

    log_category = 'dummy_agency'

    def __init__(self, testcase):
        log.Logger.__init__(self, testcase)
        log.LogProxy.__init__(self, testcase)
        self.agency_id = str(uuid.uuid1())

    @manhole.expose()
    def echo(self, text):
        return text

    def iter_agents(self):
        return iter([])


class BrokerTest(common.TestCase):

    timeout=3

    def setUp(self):
        self.brokers = [broker.Broker(DummyAgency(self)) for x in range(3)]
        self._delete_socket_file()

    @defer.inlineCallbacks
    def testInitiateMaster(self):
        for x in self.brokers:
            self.assert_role(x, broker.BrokerRole.disconnected)

        master = self.brokers[0]
        master.initiate_broker()
        self.assert_role(master, broker.BrokerRole.master)
        yield master.disconnect()
        self.assert_role(master, broker.BrokerRole.disconnected)

    @defer.inlineCallbacks
    def testIterAgencyIds(self):
        for x in self.brokers:
            yield x.initiate_broker()
        mas = list(self.brokers[0].iter_agency_ids())
        self.assertEqual(3, len(mas))
        self.assert_role(self.brokers[1], broker.BrokerRole.slave)
        sla = list(self.brokers[1].iter_agency_ids())
        self.assertEqual(1, len(sla))
        sla = list(self.brokers[2].iter_agency_ids())
        self.assertEqual(1, len(sla))

    @defer.inlineCallbacks
    def testInitiateMasterAndSlave(self):
        master = self.brokers[0]
        yield master.initiate_broker()
        slave = self.brokers[1]

        d = self.cb_after(None, master, 'append_slave')
        yield slave.initiate_broker()

        self.assert_role(master, broker.BrokerRole.master)
        self.assert_role(slave, broker.BrokerRole.slave)

        yield d
        self.assertEquals(1, len(master.slaves))
        self.assertEquals(1, len(master.factory.connections))

        slave = first(master.iter_slaves())
        result = yield slave.callRemote('echo', "hello world!")
        self.assertEqual("hello world!", result)

    @defer.inlineCallbacks
    def testSlaveComesAndGoes(self):
        master = self.brokers[0]
        yield master.initiate_broker()
        slave = self.brokers[1]

        yield slave.initiate_broker()

        slave.disconnect()
        yield common.delay(None, 0.1)

        self.assertEquals(0, len(master.slaves))
        self.assertEquals(0, len(master.factory.connections))

    @defer.inlineCallbacks
    def testMasterGoesSlaveTakesOver(self):
        master = self.brokers[0]
        yield master.initiate_broker()
        slave = self.brokers[1]
        yield slave.initiate_broker()

        self.log('Disconnecting master')
        yield master.disconnect()
        yield slave.wait_for_state(broker.BrokerRole.master)
        self.assert_role(master, broker.BrokerRole.disconnected)
        self.assert_role(slave, broker.BrokerRole.master)

    @defer.inlineCallbacks
    def testStaleSocketFileExists(self):
        # touch file
        open(self.brokers[0].socket_path, 'w').close()
        master = self.brokers[0]
        yield master.initiate_broker()
        self.assert_role(master, broker.BrokerRole.master)
        yield master.disconnect()
        self.assert_role(master, broker.BrokerRole.disconnected)

    @defer.inlineCallbacks
    def testThreeBrokersMasterDisconnects(self):
        master, slave1, slave2 = self.brokers
        for x in self.brokers:
            yield x.initiate_broker()
        self.assert_role(master, broker.BrokerRole.master)
        self.assertEqual(2, len(master.slaves))

        self.assert_role(slave1, broker.BrokerRole.slave)
        self.assert_role(slave2, broker.BrokerRole.slave)

        yield master.disconnect()
        yield common.delay(None, 0.2)
        new_master = [x for x in (slave1, slave2, )\
                      if x._cmp_state(broker.BrokerRole.master)][0]
        self.assertEqual(1, len(new_master.slaves))

        yield master.initiate_broker()
        self.assertEqual(2, len(new_master.slaves))
        self.assert_role(master, broker.BrokerRole.slave)

    @defer.inlineCallbacks
    def testPusingEventsSlaveToMaster(self):
        master, slave1, slave2 = self.brokers
        for x in self.brokers:
            yield x.initiate_broker()
        d = master.wait_event('some', 'event')
        yield slave1.push_event('some', 'event')
        yield d

    @defer.inlineCallbacks
    def testPusingEventsMasterToSlaves(self):
        master, slave1, slave2 = self.brokers
        for x in self.brokers:
            yield x.initiate_broker()
        d1 = slave1.wait_event('some', 'event')
        d2 = slave2.wait_event('some', 'event')
        yield self._wait_for_events_registered(master, 2, 'some', 'event')
        yield master.push_event('some', 'event')
        yield d1
        yield d2

    @defer.inlineCallbacks
    def testSharedState(self):
        master, slave1, slave2 = self.brokers
        for x in master, slave1:
            yield x.initiate_broker()

        # test basic setting

        master.shared_state['key'] = 'value'
        self.assertIn('key', master.shared_state)
        self.assertEquals('value', master.shared_state['key'])

        yield common.delay(None, 0.1)
        self.assertIn('key', slave1.shared_state)
        self.assertEquals('value', slave1.shared_state['key'])
        yield slave2.initiate_broker()
        yield common.delay(None, 0.1)
        self.assertIn('key', slave2.shared_state)
        self.assertEquals('value', slave2.shared_state['key'])
        slave2.shared_state['key'] = 'other value'
        self.assertEqual('other value', slave2.shared_state['key'])
        yield common.delay(None, 0.1)
        self.assertEqual('other value', master.shared_state['key'])

        # test deleting

        yield slave1.disconnect()
        del(slave2.shared_state['key'])
        self.assertNotIn('key', slave2.shared_state)
        yield common.delay(None, 0.1)
        self.assertNotIn('key', master.shared_state)

        yield slave1.initiate_broker()
        yield common.delay(None, 0.1)
        self.assertNotIn('key', slave1.shared_state)

        # test clear() method
        master.shared_state['new_key'] = 2
        yield common.delay(None, 0.1)
        slave1.shared_state.clear()
        self.assertNotIn('new_key', slave1.shared_state)
        yield common.delay(None, 0.1)
        self.assertNotIn('new_key', slave2.shared_state)
        self.assertNotIn('new_key', master.shared_state)

        # test pop() method
        master.shared_state['new_key'] = 2
        yield common.delay(None, 0.1)
        self.assertIn('new_key', slave2.shared_state)
        self.assertEqual(2, slave2.shared_state.pop('new_key'))
        self.assertNotIn('new_key', slave2.shared_state)
        yield common.delay(None, 0.1)
        self.assertNotIn('new_key', slave2.shared_state)
        self.assertNotIn('new_key', slave1.shared_state)
        self.assertNotIn('new_key', master.shared_state)

        # test popitem() method
        master.shared_state['new_key'] = 2
        yield common.delay(None, 0.1)
        self.assertEqual(('new_key', 2), slave2.shared_state.popitem())
        self.assertNotIn('new_key', slave2.shared_state)
        yield common.delay(None, 0.1)
        self.assertNotIn('new_key', slave2.shared_state)
        self.assertNotIn('new_key', slave1.shared_state)

        # test update() method
        to_update = dict(a=3, b=5)
        slave1.shared_state.update(to_update)
        self.assertIn('a', slave1.shared_state)
        self.assertIn('b', slave1.shared_state)
        self.assertEqual(3, slave1.shared_state['a'])
        self.assertEqual(5, slave1.shared_state['b'])
        yield common.delay(None, 0.1)
        self.assertIn('a', master.shared_state)
        self.assertIn('b', master.shared_state)
        self.assertEqual(3, master.shared_state['a'])
        self.assertEqual(5, master.shared_state['b'])
        self.assertIn('a', slave2.shared_state)
        self.assertIn('b', slave2.shared_state)
        self.assertEqual(3, slave2.shared_state['a'])
        self.assertEqual(5, slave2.shared_state['b'])

    @defer.inlineCallbacks
    def testFailingEventsMasterToSlaves(self):
        fail = failure.Failure(RuntimeError('failed'))
        master, slave1, slave2 = self.brokers
        for x in self.brokers:
            yield x.initiate_broker()
        d1 = slave1.wait_event('some', 'event')
        self.assertFailure(d1, Exception)
        yield self._wait_for_events_registered(master, 1, 'some', 'event')
        yield master.fail_event(fail, 'some', 'event')
        yield d1

    @defer.inlineCallbacks
    def testFailingEventsSlaveToMaster(self):
        fail = failure.Failure(RuntimeError('failed'))
        master, slave1, slave2 = self.brokers
        for x in self.brokers:
            yield x.initiate_broker()
        d1 = master.wait_event('some', 'event')
        self.assertFailure(d1, Exception)
        yield self._wait_for_events_registered(master, 1, 'some', 'event')
        yield slave1.fail_event(fail, 'some', 'event')
        yield d1

    @defer.inlineCallbacks
    def _wait_for_events_registered(self, broker, num, *args):
        key = broker._event_key(*args)
        while len(broker.notifier._notifications.get(key, list())) < num:
            yield common.delay(None, 0.1)

    @defer.inlineCallbacks
    def testPusingEventsSlaveToSlave(self):
        master, slave1, slave2 = self.brokers
        for x in self.brokers:
            yield x.initiate_broker()
        d = slave1.wait_event('some', 'event')
        yield self._wait_for_events_registered(master, 1, 'some', 'event')
        yield slave2.push_event('some', 'event')
        yield d

    @defer.inlineCallbacks
    def tearDown(self):
        for x in self.brokers:
            if not x._cmp_state(broker.BrokerRole.disconnected):
                yield x.disconnect()
        self._delete_socket_file()

    def _delete_socket_file(self):
        try:
            os.unlink(self.brokers[0].socket_path)
        except OSError:
            pass

    def assert_role(self, broker, role):
        self.assertEqual(role, broker._get_machine_state())
