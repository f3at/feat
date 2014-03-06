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

import functools
import os
import sys

from twisted.internet import reactor
from twisted.internet.error import (CannotListenError, ConnectionRefusedError,
                                    ConnectionDone, ConnectError)
from twisted.spread import pb, jelly

from feat.common import log, enum, defer, first, error, manhole, time
from feat.agencies import common

from feat.interface.agent import AgencyAgentState
from feat.agencies.agency import AgencyAgent
from feat.configure import configure

DEFAULT_SOCKET_PATH = os.path.join(configure.socketdir, 'feat-master.socket')


class TypedReference(object):
    '''
    I wrap arround the pb.RemoteReference and delegate the method calls to it.
    The point of my existance is to store remote references with the
    information about the type of object they point to.
    '''

    def __init__(self, reference):
        self.reference = reference

    def callRemote(self, _method, *args, **kwargs):
        return self.reference.callRemote(_method, *args, **kwargs)

    def get_status(self):
        d = self.callRemote('get_status')
        d.addCallback(AgencyAgentState.get) #@UndefinedVariable
        return d


class SlaveReference(TypedReference):

    def __init__(self, broker, slave_id, reference, is_standalone):
        TypedReference.__init__(self, reference)

        # pb.RemoteReference to the Broker instance
        self.broker = broker
        # agency id
        self.slave_id = slave_id
        # bool flag saying if it is a standalone agency
        self.is_standalone = is_standalone
        # agent_id -> pb.Reference to AgencyAgent instance
        self.agents = dict()

    def register_agent(self, agent_id, reference):
        self.agents[agent_id] = AgentReference(reference, agent_id)

    def unregister_agent(self, agent_id):
        del(self.agents[agent_id])


class AgentReference(TypedReference):

    def __init__(self, reference, agent_id):
        TypedReference.__init__(self, reference)
        self.agent_id = agent_id


class SharedState(dict):

    def __init__(self, broker, items=[]):
        dict.__init__(self, items)
        self._broker = broker

    ### dict implementation ###

    def __setitem__(self, key, value):
        self.set_locally(key, value)
        self._broker.update_state_broadcast('set_locally', key, value)

    def __delitem__(self, key):
        self.del_locally(key)
        self._broker.update_state_broadcast('del_locally', key)

    def clear(self):
        self.clear_locally()
        self._broker.update_state_broadcast('clear_locally')

    def pop(self, key):
        if key not in self:
            raise KeyError("%s key not found!")
        res = dict.pop(self, key)
        self._broker.update_state_broadcast('del_locally', key)
        return res

    def popitem(self):
        key, value = dict.popitem(self)
        self._broker.update_state_broadcast('del_locally', key)
        return key, value

    def update(self, dict_):
        self.update_locally(dict_.items())
        self._broker.update_state_broadcast('update_locally', dict_.items())

    ### local modifications ###

    def set_locally(self, key, value):
        dict.__setitem__(self, key, value)

    def del_locally(self, key):
        if key in self:
            dict.__delitem__(self, key)

    def clear_locally(self):
        for key in self.keys():
            self.del_locally(key)

    def reset_locally(self, items):
        self.clear_locally()
        self.update_locally(items)

    def update_locally(self, items):
        for key, value in items:
            self.set_locally(key, value)


class BrokerRole(enum.Enum):

    disconnected, master, slave = range(3)


class Broker(log.Logger, log.LogProxy, common.StateMachineMixin,
             manhole.Manhole, pb.Root):
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
                 on_master_missing_cb=None, standalone=False):
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
        self.on_master_missing_cb = on_master_missing_cb

        self.shared_state = SharedState(self)
        self._set_idle(True)

    def is_master(self):
        return self._cmp_state(BrokerRole.master)

    def is_slave(self):
        return self._cmp_state(BrokerRole.slave)

    def is_idle(self):
        return self._idle

    def initiate_broker(self):
        self._set_idle(False)

        if not self._is_standalone:
            try:
                self.factory = MasterFactory(self)
                self.listener = reactor.listenUNIX( #@UndefinedVariable
                                                   self.socket_path,
                                                   self.factory,
                                                   mode=self.socket_mode)
                d = defer.succeed(None)
                d.addCallback(defer.drop_param, self.become_master)
                d.addBoth(defer.bridge_param, self._set_idle, True)
                return d
            except CannotListenError as e:
                self.info('Cannot listen on socket: %r. '\
                          'Assuming slave role.', e)
                return self._connect_as_slave()
        elif self._is_standalone:
            self.info('Standalone role')
            return self._connect_as_slave()

    def _connect_as_slave(self):
        cb = defer.Deferred()
        self.factory = SlaveFactory(self, cb)
        self.connector = reactor.connectUNIX( #@UndefinedVariable
            self.socket_path, self.factory, timeout=1)
        cb.addBoth(defer.bridge_param, self._set_idle, True)
        return cb

    def disconnect(self):
        '''
        This is called as part of the agency shutdown.
        '''
        self.log("Disconnecting broker %r.", self)
        d = defer.succeed(None)
        if self.is_master():
            if self.listener is not None:
                d.addCallback(defer.drop_param, self.listener.stopListening)
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
            if os.path.exists(self.socket_path):
                os.unlink(self.socket_path)
        except OSError as e:
            self.error('Failed to remove socket file: %s, reason: %r',
                       self.socket_path, e)

    # Server specific

    def remote_handshake(self, broker, slave, agency_id, standalone):
        self.debug('Appending slave agency. Agency id: : %s', agency_id)
        self.append_slave(broker, agency_id, slave, standalone)
        slave.notifyOnDisconnect(self.remove_slave(agency_id))
        return self.shared_state.items()

    def remote_register_agent_local(self, slave_id, agent_id, reference):
        slave = self.slaves[slave_id]
        slave.register_agent(agent_id, reference)

    def remote_unregister_agent_local(self, slave_id, agent_id):
        slave = self.slaves[slave_id]
        slave.unregister_agent(agent_id)

    def remote_get_agency_id(self):
        return self.agency.agency_id

    def iter_slaves(self):
        return (slave.reference for slave in self.slaves.itervalues())

    def iter_slave_references(self):
        return (slave for slave in self.slaves.itervalues())

    def has_slave(self):
        '''Returns True/False wether we have a slave agency which is not
        standalone running.'''
        slave = first(x for x in self.slaves.itervalues()
                      if not x.is_standalone)
        return slave is not None

    def get_agent_reference(self, agent_id):
        for slave in self.slaves.itervalues():
            if agent_id in slave.agents:
                return slave.agents[agent_id]
        return None

    @manhole.expose()
    def shutdown_slaves(self, gentle=False):

        def error_handler(f):
            if f.check(ConnectionDone, pb.PBConnectionLost):
                self.log('Swallowing %r - this is expected result.',
                         f.value.__class__.__name__)
            else:
                f.raiseException()

        if self.is_master():

            def kill_slave(slave):
                self.log('slave is %r', slave)
                method_to_call = 'shutdown' if gentle else 'kill'
                d = slave.callRemote(method_to_call, stop_process=True)
                d.addErrback(error_handler)
                return d

            return defer.DeferredList([kill_slave(x)
                                       for x in self.iter_slaves()])
        elif self.is_slave():
            d = self._master.callRemote('shutdown_slaves')
            d.addErrback(error_handler)
            return d

    def append_slave(self, broker, slave_id, slave, standalone):
        self.slaves[slave_id] = SlaveReference(broker, slave_id,
                                               slave, standalone)

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

    def become_slave(self, broker):
        '''
        Run as part of the handshake.
        @param broker: Remote reference to the broker object
        '''
        self._set_state(BrokerRole.slave)
        self._master = broker
        d = defer.succeed(None)
        if callable(self.on_slave_cb):
            d.addCallback(defer.drop_param, self.on_slave_cb)

        d.addCallback(defer.drop_param, self._master.callRemote,
                      'handshake', self, self.agency, self.agency.agency_id,
                      self.is_standalone())
        d.addCallback(defer.inject_param, 1, self.update_state,
                      'reset_locally')

        for medium in self.agency.iter_agents():
            d.addCallback(defer.drop_param, self.register_agent, medium)

        return d

    def fetch_master_id(self):
        if not self._master:
            return defer.succeed(None)
        return self._master.callRemote('get_agency_id')

    # ............

    def become_disconnected(self):
        previous_state = self.state
        self._set_state(BrokerRole.disconnected)
        if callable(self.on_disconnected_cb):
            return self.on_disconnected_cb(previous_state)

    def missing_master(self):
        pass

    # events

    @manhole.expose()
    def wait_event(self, *args):
        self._ensure_connected()
        if self.is_master():
            self.debug('Registering listener for event %r', args)
            key = self._event_key(*args)
            return self.notifier.wait(key)
        elif self.is_slave():
            return self._master.callRemote('wait_event', *args)

    @manhole.expose()
    def push_event(self, *args):
        self._ensure_connected()
        if self.is_master():
            self.debug("Triggering event listeners for the args %r.", args)
            key = self._event_key(*args)
            self.notifier.callback(key, None)
        elif self.is_slave():
            self.debug("Notifying master about successful event for the "
                       "args %r.", args)
            return self._master.callRemote('push_event', *args)

    @manhole.expose()
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

    @manhole.expose()
    def start_agent(self, desc, *args, **kwargs):
        self._ensure_connected()
        if self.is_master():
            return self.agency.actually_start_agent(desc, *args, **kwargs)
        elif self.is_slave():
            return self._master.callRemote(
                'start_agent', desc, *args, **kwargs)

    @manhole.expose()
    def get_agency(self):
        return self.agency

    @manhole.expose()
    @defer.inlineCallbacks
    def find_agent(self, agent_id):
        #FIXME: find_agent() is broken when a slave
        #       lookup an agent from another slave.
        self._ensure_connected()
        if self.is_master():
            # look locally
            local = yield self.agency.find_agent_locally(agent_id)
            if local:
                defer.returnValue(local)
            # check for slaves
            for slave in self.iter_slave_references():
                if agent_id in slave.agents:
                    defer.returnValue(slave.agents[agent_id])
            # give up
            defer.returnValue(None)
        elif self.is_slave():
            #FIXME: something's broken or incosistent in the whole find_agent
            #       breaking f.t.i.test_agencies_net_agency
            res = yield self._master.callRemote('find_agent', agent_id)
            if isinstance(res, pb.RemoteReference):
                defer.returnValue(AgentReference(res, agent_id))
            if isinstance(res.reference, AgencyAgent):
                defer.returnValue(res.reference)
            defer.returnValue(res)

    @manhole.expose()
    def broadcast_force_snapshot(self):
        self._ensure_connected()
        if self.is_master():
            defers = list()
            for slave in self.iter_slaves():
                defers.append(slave.callRemote('snapshot_agents', force=True))
            return defer.DeferredList(defers, consumeErrors=True)

    @manhole.expose()
    def get_journaler(self):
        self._ensure_connected()
        if self.is_master():
            return self.agency._journaler
        elif self.is_slave():
            return self._master.callRemote('get_journaler')

    def iter_agency_ids(self):
        self._ensure_connected()
        if self.is_master():
            return iter([self.agency.agency_id] + self.slaves.keys())
        elif self.is_slave():
            return iter([self.agency.agency_id])

    def register_agent(self, medium):
        if self.is_slave():
            agent_id = medium.get_agent_id()
            return self._master.callRemote('register_agent_local',
                                           self.agency.agency_id,
                                           agent_id, medium)

    def unregister_agent(self, medium):
        agent_id = medium.get_agent_id()
        if self.is_slave():
            return self._master.callRemote(
                'unregister_agent_local', self.agency.agency_id, agent_id)

    @manhole.expose()
    def get_broker_backend(self):
        if self.is_slave():
            return self._master.callRemote('get_broker_backend')
        else:
            return self.agency.get_broker_backend()

    def is_standalone(self):
        return self._is_standalone

    @manhole.expose()
    def update_state(self, _method, *args, **kwargs):
        method = getattr(self.shared_state, _method, None)
        if not callable(method):
            raise AttributeError("Uknown update_state() param, method: %s"
                                 % _method)
        return method(*args, **kwargs)

    @manhole.expose()
    def update_state_broadcast(self, _method, *args, **kwargs):
        origin_id = kwargs.pop('agency_id', self.agency.agency_id)

        self._ensure_connected()
        if self._cmp_state(BrokerRole.master):
            defers = list()
            if origin_id != self.agency.agency_id:
                self.update_state(_method, *args, **kwargs)
            for slave in self.iter_slave_references():
                if slave.slave_id != self.agency.agency_id:
                    defers.append(
                        slave.broker.callRemote(
                            'update_state', _method, *args, **kwargs))
            return defer.DeferredList(defers, consumeErrors=True)
        elif self._cmp_state(BrokerRole.slave):
            return self._master.callRemote('update_state_broadcast',
                                           _method, agency_id=origin_id,
                                           *args, **kwargs)

    ### private ###

    def _set_idle(self, value):
        self._idle = value


class MasterFactory(pb.PBServerFactory, log.Logger):

    def __init__(self, broker):
        log.Logger.__init__(self, broker)
        pb.PBServerFactory.__init__(self, broker,
                                    security=jelly.DummySecurityOptions())

        self.broker = broker
        self.connections = list()

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
        pb.PBClientFactory.__init__(
            self, security=jelly.DummySecurityOptions())
        log.Logger.__init__(self, broker)
        self.broker = broker
        self.deferred = cb

    def clientConnectionFailed(self, connector, reason):
        pb.PBClientFactory.clientConnectionFailed(self, connector, reason)
        self.info('Client connection failed!. Reason: %r', reason)

        if reason.check(ConnectError):
            if not self.broker.is_standalone():
                self.broker.remove_stale_socket()
            else:
                self.broker.missing_master()

        if reason.check(ConnectionRefusedError):
            self.broker.remove_stale_socket()
            d = self.broker.initiate_broker()
            d.addCallback(self.deferred.callback)

    def clientConnectionMade(self, broker):
        pb.PBClientFactory.clientConnectionMade(self, broker)
        self.log('Slave broker connection made.')

        d = defer.succeed(None)
        d.addCallback(defer.drop_param, self.getRootObject)
        d.addCallback(self.broker.become_slave)
        d.addCallback(defer.drop_param, self.deferred.callback, None)

    def clientConnectionLost(self, connector, reason, reconnecting=0):
        pb.PBClientFactory.clientConnectionLost(self, connector, reason)
        self.debug('Lost slave broker connection. Reason: %r', reason)
        if not self.broker._cmp_state(BrokerRole.disconnected):
            d = defer.succeed(None)
            d.addCallback(defer.drop_param, self.broker.become_disconnected)
            d.addCallback(defer.drop_param, self.broker.initiate_broker)
            return d


class StandaloneBroker(Broker):

    def __init__(self, *args, **kwargs):
        Broker.__init__(self, *args, **kwargs)
        self._is_standalone = True
        self._reconn_dc = None

    def missing_master(self):
        self._reconn_dc = time.callLater(5, self.initiate_broker)
        return self.spawn_missing_master()

    def spawn_missing_master(self):
        '''
        Notifies the standalone slave agency that the master agency is missing
        '''
        d = defer.succeed(None)
        if callable(self.on_master_missing_cb):
            d.addCallback(defer.drop_param, self.on_master_missing_cb)
        return d

    def disconnect(self):
        if self._reconn_dc is not None and self._reconn_dc.active():
            self._reconn_dc.cancel()
        return Broker.disconnect(self)
