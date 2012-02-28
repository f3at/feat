import os
import uuid

from twisted.spread import pb

from feat.test import common

from feat.agencies import recipient, message

from feat.agencies.net import broker
from feat.agencies.messaging import messaging, unix

from feat.common import defer, log, time


class DummyChannel(messaging.Channel):

    def __init__(self, _messaging):
        messaging.Channel.__init__(self, _messaging, agent=None)
        self.messages = dict()

    #overwriten on_message() to make asserts

    def on_message(self, message):
        self.messages[message.message_id] = message
        self.log('got message, now we have %d', len(self.messages))

    def has_messages(self, num):

        def has_messages():
            return len(self.messages) == num

        return has_messages


class DummyAgency(pb.Referenceable, log.Logger, log.LogProxy):

    def __init__(self, logger):
        log.LogProxy.__init__(self, logger)
        log.Logger.__init__(self, self)

        self.agency_id = str(uuid.uuid1())

        self.broker = broker.Broker(
            self,
            on_master_cb=self.on_become_master,
            on_slave_cb=self.on_become_slave,
            on_disconnected_cb=self.on_broker_disconnect)

        self.messaging = messaging.Messaging(logger)

    def initiate(self):
        return self.broker.initiate_broker()

    def cleanup(self):
        return self.broker.disconnect()

    def on_become_master(self):
        backend = unix.Master(self.broker)
        return self.messaging.add_backend(backend, can_become_outgoing=False)

    def on_become_slave(self):
        backend = unix.Slave(self.broker)
        return self.messaging.add_backend(backend)

    def on_broker_disconnect(self, pre_state):
        self.messaging.remove_backend('unix')

    def get_broker_backend(self):
        if self.broker.state != broker.BrokerRole.master:
            raise RuntimeError("We are not master, wtf?!")
        return self.messaging._backends['unix']

    def get_connection(self):
        c = DummyChannel(self.messaging)
        return c.initiate()

    def iter_agents(self): #needed when we become slave
        return iter([])


def msg():
    m = message.BaseMessage(
        expiration_time=time.time() + 5,
        message_id=str(uuid.uuid1()))
    return m


class UnixSocketMessagingTest(common.TestCase):

    def setUp(self):
        self.agencies = [DummyAgency(self) for x in range(3)]
        self._delete_socket_file()

    @defer.inlineCallbacks
    def tearDown(self):
        for agency in self.agencies:
            yield agency.cleanup()
        yield common.TestCase.tearDown(self)

    @defer.inlineCallbacks
    def testMessagesAndBindings(self):
        connections = list()
        for index in range(3):
            yield self.agencies[index].initiate()
            self.assertTrue('unix' in self.agencies[index].messaging._backends)
            con = yield self.agencies[index].get_connection()
            connections.append(con)

        recp = recipient.Agent('agent_id', 'shard')
        connections[1].create_binding(recp)
        connections[0].post(recp, msg())

        yield self.wait_for(connections[1].has_messages(1), 1, 0.02)

        broadcast = recipient.Broadcast('some_brodcast', 'shard')
        bindings = [con.create_binding(broadcast) for con in connections]

        connections[0].post(broadcast, msg())
        yield self.wait_for(connections[0].has_messages(1), 1, 0.02)
        yield self.wait_for(connections[1].has_messages(2), 1, 0.02)
        yield self.wait_for(connections[2].has_messages(1), 1, 0.02)

        connections[1].post(broadcast, msg())
        yield self.wait_for(connections[0].has_messages(2), 1, 0.02)
        yield self.wait_for(connections[1].has_messages(3), 1, 0.02)
        yield self.wait_for(connections[2].has_messages(2), 1, 0.02)

        connections[1].revoke_binding(bindings[1])
        connections[2].post(broadcast, msg())
        yield self.wait_for(connections[0].has_messages(3), 1, 0.02)
        yield self.wait_for(connections[1].has_messages(3), 1, 0.02)
        yield self.wait_for(connections[2].has_messages(3), 1, 0.02)

    def _delete_socket_file(self):
        try:
            os.unlink(self.agencies[0].broker.socket_path)
        except OSError:
            pass
