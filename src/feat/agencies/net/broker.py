import os
import functools

from twisted.internet import reactor
from twisted.internet.error import (CannotListenError, ConnectionRefusedError,
                                    ConnectionDone, )
from twisted.spread import pb

from feat.common import log, enum, defer, first, error
from feat.common.serialization import banana
from feat.agencies import common


DEFAULT_SOCKET_PATH = "/tmp/feat-master.socket"


class SlaveReference(object):

    def __init__(self, slave_id, reference, is_standalone):
        # agency id
        self.slave_id = slave_id
        # pb.Reference to the Agency instance
        self.reference = reference
        # bool flag saying if it is a standalone agency
        self.is_standalone = is_standalone
        # agent_id -> pb.Reference to AgencyAgent instance
        self.agents = dict()

    def callRemote(self, _method, *args, **kwargs):
        return self.reference.callRemote(_method, *args, **kwargs)

    def register_agent(self, agent_id, reference):
        self.agents[agent_id] = reference

    def unregister_agent(self, agent_id):
        del(self.agents[agent_id])


class BrokerRole(enum.Enum):

    disconnected, master, slave = range(3)


class Broker(log.Logger, log.LogProxy, common.StateMachineMixin):
    '''
    Mixin for the network agency. It is responsible on connecting/listening
    on the unix socket. The broker which manages to listen is taking the master
    role and keeps track of the rest of the instances.
    '''

    default_socket_path = DEFAULT_SOCKET_PATH
    socket_mode = 666

    def __init__(self, agency, socket_path=None,
                 on_master_cb=None, on_slave_cb=None,
                 on_disconnected_cb=None, on_remove_slave_cb=None,
                 standalone=False):
        log.Logger.__init__(self, agency)
        log.LogProxy.__init__(self, agency)
        common.StateMachineMixin.__init__(self, BrokerRole.disconnected)
        self.agency = agency

        self.connector = None
        self.listener = None
        self.socket_path = socket_path or self.default_socket_path
        self.factory = None
        self._is_standalone = standalone
        # agency_id -> pb.RemoteReference to Agency
        self.slaves = dict()
        self.notifier = defer.Notifier()

        self.on_master_cb = on_master_cb
        self.on_slave_cb = on_slave_cb
        self.on_disconnected_cb = on_disconnected_cb
        self.on_remove_slave_cb = on_remove_slave_cb

        self._serializer = banana.Serializer()

    def is_master(self):
        return self._cmp_state(BrokerRole.master)

    def is_slave(self):
        return self._cmp_state(BrokerRole.slave)

    def initiate_broker(self):
        if not self._is_standalone:
            try:
                self.factory = MasterFactory(self)
                self.listener = reactor.listenUNIX(self.socket_path,
                                                   self.factory,
                                                   mode=self.socket_mode)
                d = defer.succeed(None)
                d.addCallback(defer.drop_param, self.become_master)
                d.addErrback(self._handle_critical_error)
                return d
            except CannotListenError as e:
                self.info('Cannot listen on socket: %r. '\
                          'Assuming slave role.', e)
                return self._connect_as_slave()
        elif self._is_standalone:
            self.info('Standalone role')
            return self._connect_as_slave()

    def _handle_critical_error(self, fail):
        self.error("I'm killing the process, goodbye!")
        error.handle_failure(self, fail, 'Critical error occured.')
        self.agency.shutdown(stop_process=True)

    def _connect_as_slave(self):
        cb = defer.Deferred()
        self.factory = SlaveFactory(self, cb)
        self.connector = reactor.connectUNIX(
            self.socket_path, self.factory, timeout=1)
        return cb

    def disconnect(self):
        '''
        This is called as part of the agency shutdown.
        '''
        self.log("Disconnecting broker %r.", self)
        if self.is_master():
            d = self.listener.stopListening()
            d.addCallback(defer.drop_param, self.factory.disconnect)
        elif self.is_slave():
            d = defer.maybeDeferred(self.factory.disconnect)
        elif self._cmp_state(BrokerRole.disconnected):
            return defer.succeed(None)
        d.addCallback(defer.drop_param, self.become_disconnected)
        return d

    def remove_stale_socket(self):
        self.debug('Removing stale socket file at: %s', self.socket_path)
        try:
            os.unlink(self.socket_path)
        except OSError as e:
            self.error('Failed to remove socket file: %s, reason: %r',
                       self.socket_path, e)

    # Server specific

    def iter_slaves(self):
        return (slave.reference for slave in self.slaves.itervalues())

    def has_slave(self):
        '''Returns True/False wether we have a slave agency which is not
        standalone running.'''
        slave = first(x for x in self.slaves.itervalues()
                      if not x.is_standalone)
        return slave is not None

    def shutdown_slaves(self):
        if self.is_master():

            def error_handler(f):
                if f.check(ConnectionDone, pb.PBConnectionLost):
                    self.log('Swallowing %r - this is expected result.',
                             f.value.__class__.__name__)
                else:
                    f.raiseException()

            def kill_slave(slave):
                self.log('slave is %r', slave)
                d = slave.callRemote('shutdown', stop_process=True)
                d.addErrback(error_handler)
                return d

            return defer.DeferredList([kill_slave(x)
                                       for x in self.iter_slaves()])
        elif self.is_slave():
            self._master.callRemote('shutdown_slaves')

    def append_slave(self, slave_id, slave, standalone):
        self.slaves[slave_id] = SlaveReference(slave_id, slave, standalone)

    def remove_slave(self, slave_id):

        def do_remove(slave):
            self.log('Removing slave agency.')
            try:
                del(self.slaves[slave_id])
                if callable(self.on_remove_slave_cb):
                    return self.on_remove_slave_cb()
            except ValueError:
                self.error("Slave %r not found. ID: %r, Slaves: %r",
                           slave, slave_id, self.slaves)
        return do_remove

    def become_master(self):
        self._set_state(BrokerRole.master)
        if callable(self.on_master_cb):
            return self.on_master_cb()

    # Slave/Standalone specific

    def become_slave(self, root):
        '''
        Run as part of the handshake.
        @param master: Remote reference to the root object (PBServerFactory)
        '''
        self._set_state(BrokerRole.slave)
        self._master = root
        if callable(self.on_slave_cb):
            return self.on_slave_cb()

    # ............

    def become_disconnected(self):
        previous_state = self.state
        self._set_state(BrokerRole.disconnected)
        if callable(self.on_disconnected_cb):
            return self.on_disconnected_cb(previous_state)

    # events

    def wait_event(self, *args):
        self._ensure_connected()
        if self.is_master():
            self.debug('Registering event for args %r', args)
            key = self._event_key(*args)
            return self.notifier.wait(key)
        elif self.is_slave():
            return self._master.callRemote('wait_event', *args)

    def push_event(self, *args):
        self._ensure_connected()
        if self.is_master():
            self.debug("Triggering events for the args %r.", args)
            key = self._event_key(*args)
            self.notifier.callback(key, None)
        elif self.is_slave():
            return self._master.callRemote('push_event', *args)

    def fail_event(self, failure, *args):
        self._ensure_connected()
        if self.is_master():
            self.debug("Errbacking events for the args %r Failure: %r",
                       args, failure)
            failure = pb.Error(failure)
            key = self._event_key(*args)
            self.notifier.errback(key, failure)
        elif self.is_slave():
            return self._master.callRemote('fail_event', failure, *args)

    def _ensure_connected(self):
        if self._cmp_state(BrokerRole.disconnected):
            raise RuntimeError("Events can only work on connected broker")

    def _event_key(self, *args):
        return tuple(args)

    def start_agent(self, desc, *args, **kwargs):
        self._ensure_connected()
        if self.is_master():
            return self.agency.actually_start_agent(desc, *args, **kwargs)
        elif self.is_slave():
            self._unserializer = banana.Unserializer()
            raw_desc = self._serializer.convert(desc)
            return self._master.callRemote(
                'start_agent', raw_desc, *args, **kwargs)

    def find_agent(self, agent_id):
        self._ensure_connected()
        if self.is_master():
            return self.agency._find_agent(agent_id)
        elif self.is_slave():
            return self._master.callRemote('find_agent', agent_id)

    def get_journal_writer(self):
        self._ensure_connected()
        if self.is_master():
            return self.agency.get_journal_writer()
        elif self.is_slave():
            return self._master.callRemote('get_journal_writer')

    def iter_agency_ids(self):
        self._ensure_connected()
        if self.is_master():
            res = [self.agency.agency_id] + self.slaves.keys()
            return res.__iter__()
        elif self.is_slave():
            res = [self.agency.agency_id]
            return res.__iter__()

    def register_agent(self, medium):
        agent_id = medium.get_agent_id()
        if self.is_slave():
            return self._master.callRemote(
                'register_agent', self.agency.agency_id, agent_id, medium)

    def unregister_agent(self, medium):
        agent_id = medium.get_agent_id()
        if self.is_slave():
            return self._master.callRemote(
                'unregister_agent', self.agency.agency_id, agent_id)

    def is_standalone(self):
        return self._is_standalone


class MasterFactory(pb.PBServerFactory, pb.Root, log.Logger):

    def __init__(self, broker):
        log.Logger.__init__(self, broker)
        pb.PBServerFactory.__init__(self, self)
        self.broker = broker
        self.connections = list()

        self._unserializer = banana.Unserializer()

    def remote_handshake(self, slave, agency_id, standalone):
        self.debug('Appending slave agency: %r', slave)
        self.broker.append_slave(agency_id, slave, standalone)
        slave.notifyOnDisconnect(self.broker.remove_slave(agency_id))

    def remote_wait_event(self, *args):
        return self.broker.wait_event(*args)

    def remote_push_event(self, *args):
        return self.broker.push_event(*args)

    def remote_fail_event(self, failure, *args):
        return self.broker.fail_event(failure, *args)

    def remote_find_agent(self, agent_id):
        return self.broker.find_agent(agent_id)

    def remote_shutdown_slaves(self):
        return self.broker.shutdown_slaves()

    def remote_start_agent(self, raw_desc, *args, **kwargs):
        desc = self._unserializer.convert(raw_desc)
        return self.broker.start_agent(desc, *args, **kwargs)

    def remote_get_journal_writer(self):
        return self.broker.get_journal_writer()

    def remote_register_agent(self, slave_id, agent_id, reference):
        slave = self.broker.slaves[slave_id]
        slave.register_agent(agent_id, reference)

    def remote_unregister_agent(self, slave_id, agent_id):
        slave = self.broker.slaves[slave_id]
        slave.unregister_agent(agent_id)

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
        d.addErrback(self.broker._handle_critical_error)
        d.addCallback(defer.drop_param, self.getRootObject)
        d.addCallback(defer.call_param, 'callRemote', 'handshake',
                      self.agency, self.agency.agency_id,
                      self.broker.is_standalone())
        d.addCallback(defer.drop_param, self._register_agents)
        d.addCallback(self.deferred.callback)

    def _register_agents(self):
        d = defer.succeed(None)
        for medium in self.agency.iter_agents():
            d.addCallback(defer.drop_param, self.broker.register_agent,
                          medium)
        return d

    def clientConnectionLost(self, connector, reason, reconnecting=0):
        pb.PBClientFactory.clientConnectionLost(self, connector, reason)
        self.debug('lost slave connection')
        if not self.broker._cmp_state(BrokerRole.disconnected):
            d = defer.succeed(None)
            d.addCallback(defer.drop_param, self.broker.become_disconnected)
            d.addCallback(defer.drop_param, self.broker.initiate_broker)
            return d


class StandaloneBroker(Broker):

    def __init__(self, *args, **kwargs):
        Broker.__init__(self, *args, **kwargs)
        self._is_standalone = True
