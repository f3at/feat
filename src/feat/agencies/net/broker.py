import os
import functools

from twisted.internet import reactor
from twisted.internet.error import CannotListenError, ConnectionRefusedError
from twisted.spread import pb

from feat.common import log, enum, defer
from feat.agencies import common


class BrokerRole(enum.Enum):

    disconnected, master, slave = range(3)


class Broker(log.Logger, log.LogProxy, common.StateMachineMixin):
    '''
    Mixin for the network agency. It is responsible on connecting/listening
    on the unix socket. The broker which manages to listen is taking the master
    role and keeps track of the rest of the instances.
    '''

    default_socket_path = "/tmp/feat-master.socket"
    socket_mode = 666

    log_category = "pb-broker"

    def __init__(self, agency, socket_path=None,
                 on_master_cb=None, on_slave_cb=None,
                 on_disconnected_cb=None):
        log.Logger.__init__(self, agency)
        log.LogProxy.__init__(self, agency)
        common.StateMachineMixin.__init__(self, BrokerRole.disconnected)
        self.agency = agency

        self.connector = None
        self.listener = None
        self.socket_path = socket_path or self.default_socket_path
        self.factory = None
        self.slaves = list()
        self.notifier = defer.Notifier()

        self.on_master_cb = on_master_cb
        self.on_slave_cb = on_slave_cb
        self.on_disconnected_cb = on_disconnected_cb

    def initiate_broker(self):
        try:
            self.factory = MasterFactory(self)
            self.listener = reactor.listenUNIX(self.socket_path, self.factory,
                                               mode=self.socket_mode)
            self.become_master()
            return defer.succeed(None)
        except CannotListenError as e:
            cb = defer.Deferred()
            self.factory = SlaveFactory(self, cb)
            self.info('Cannot listen on socket: %r. Assuming slave role.', e)
            self.connector = reactor.connectUNIX(
                self.socket_path, self.factory, timeout=1)
            return cb

    def disconnect(self):
        '''
        This is called as part of the agency shutdown.
        '''
        self.log("Disconnecting broker %r.", self)
        if self._cmp_state(BrokerRole.master):
            d = self.listener.stopListening()
            d.addCallback(lambda _: self.factory.disconnect())
        elif self._cmp_state(BrokerRole.slave):
            d = defer.maybeDeferred(self.factory.disconnect)
        elif self._cmp_state(BrokerRole.disconnected):
            return defer.succeed(None)
        d.addCallback(lambda _: self.become_disconnected())
        return d

    def remove_stale_socket(self):
        self.debug('Removing stale socket file at: %s', self.socket_path)
        try:
            os.unlink(self.socket_path)
        except OSError as e:
            self.error('Failed to remove socket file: %s, reason: %r',
                       self.socket_path, e)

    # Master specific

    def shutdown_slaves(self):
        self._ensure_state(BrokerRole.master)
        return defer.DeferredList([x.callRemote('kill') for x in self.slaves])

    def append_slave(self, slave):
        self.slaves.append(slave)

    def remove_slave(self, slave):
        self.log('Removing slave agency.')
        try:
            self.slaves.remove(slave)
        except ValueError:
            self.error("Slave %r not found. Slaves: %r", slave, self.slaves)

    def become_master(self):
        self._set_state(BrokerRole.master)
        if callable(self.on_master_cb):
            self.on_master_cb()

    # Slave specific

    def become_slave(self, root):
        '''
        Run as part of the handshake.
        @param master: Remote reference to the root object (PBServerFactory)
        '''
        self._set_state(BrokerRole.slave)
        self._master = root
        if callable(self.on_slave_cb):
            self.on_slave_cb()
        return root

    # ............

    def become_disconnected(self):
        self._set_state(BrokerRole.disconnected)
        if callable(self.on_disconnected_cb):
            self.on_disconnected_cb()

    # events

    def wait_event(self, *args):
        self._ensure_connected()
        if self._cmp_state(BrokerRole.master):
            self.debug('Registering event for args %r', args)
            key = self._event_key(*args)
            return self.notifier.wait(key)
        elif self._cmp_state(BrokerRole.slave):
            return self._master.callRemote('wait_event', *args)

    def push_event(self, *args):
        self._ensure_connected()
        if self._cmp_state(BrokerRole.master):
            self.debug("Triggering events for the args %r.", args)
            key = self._event_key(*args)
            self.notifier.callback(key, None)
        elif self._cmp_state(BrokerRole.slave):
            return self._master.callRemote('push_event', *args)

    def fail_event(self, failure, *args):
        self._ensure_connected()
        if self._cmp_state(BrokerRole.master):
            self.debug("Errbacking events for the args %r Failure: %r",
                       args, failure)
            failure = pb.Error(failure)
            key = self._event_key(*args)
            self.notifier.errback(key, failure)
        elif self._cmp_state(BrokerRole.slave):
            return self._master.callRemote('fail_event', failure, *args)

    def _ensure_connected(self):
        if self._cmp_state(BrokerRole.disconnected):
            raise RuntimeError("Events can only work on connected broker")

    def _event_key(self, *args):
        return tuple(args)


class MasterFactory(pb.PBServerFactory, pb.Root, log.Logger):

    log_category = "pb-master"

    def __init__(self, broker):
        log.Logger.__init__(self, broker)
        pb.PBServerFactory.__init__(self, self)
        self.broker = broker
        self.slaves = list()
        self.connections = list()

    def remote_handshake(self, slave):
        self.debug('Appending slave agency: %r', slave)
        self.broker.append_slave(slave)
        slave.notifyOnDisconnect(self.broker.remove_slave)

    def remote_wait_event(self, *args):
        return self.broker.wait_event(*args)

    def remote_push_event(self, *args):
        return self.broker.push_event(*args)

    def remote_fail_event(self, failure, *args):
        return self.broker.fail_event(failure, *args)

    def clientConnectionMade(self, broker):
        self.debug('Client connection made to the server: %r', broker)
        self.connections.append(broker)
        cb = functools.partial(self._remove_broker, broker)
        broker.notifyOnDisconnect(cb)

    def _remove_broker(self, broker):
        try:
            self.connections.remove(broker)
        except ValueError:
            self.error("Tried to remove the broker %r from the list, but "
                       "it was not found!", broker)

    def disconnect(self):
        [x.transport.loseConnection() for x in self.connections]


class SlaveFactory(pb.PBClientFactory, log.Logger):

    log_category = 'pb-slave'

    def __init__(self, broker, cb):
        pb.PBClientFactory.__init__(self)
        log.Logger.__init__(self, broker)
        self.agency = broker.agency
        self.broker = broker
        self.deferred = cb

    def clientConnectionFailed(self, connector, reason):
        pb.PBClientFactory.clientConnectionFailed(self, connector, reason)
        self.info('Client connection failed!. Reason: %r', reason)
        if reason.check(ConnectionRefusedError):
            self.broker.remove_stale_socket()
            d = self.broker.initiate_broker()
            d.addCallback(self.deferred.callback)

    def clientConnectionMade(self, broker):
        pb.PBClientFactory.clientConnectionMade(self, broker)
        self.log('Slave connection made. Broker: %r', broker)

        d = self.getRootObject()
        d.addCallback(self.broker.become_slave)
        d.addCallback(lambda x: x.callRemote('handshake', self.agency))
        d.addCallback(self.deferred.callback)

    def clientConnectionLost(self, connector, reason, reconnecting=0):
        pb.PBClientFactory.clientConnectionLost(self, connector, reason)
        self.debug('lost slave connection')
        if not self.broker._cmp_state(BrokerRole.disconnected):
            self.broker.become_disconnected()
            self.broker.initiate_broker()
