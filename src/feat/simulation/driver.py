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
import StringIO
import uuid

from feat.common import log, manhole, defer, reflect, time
from feat.agencies import journaler
from feat.database import document, emu as database, tools
from feat.agencies.messaging import emu, rabbitmq, tunneling
from feat.test import factories
from feat.agents.shard import shard_agent
from feat.simulation import agency

from feat.interface.agency import ExecMode
from feat.interface.recipient import IRecipient


class Commands(manhole.Manhole):
    '''
    Implementation of all the commands understood by the protocol.
    This is a mixin mixed to Driver class.
    '''

    @manhole.expose()
    def load(self, module):
        reflect.named_module(module)

    @manhole.expose()
    def spawn_agency(self, *components, **kwargs):
        '''
        Spawn new agency, returns the reference. Usage:
        > spawn_agency()
        Also takes a list of components to switch into production mode.
        By default all the components work in test mode.
        Components are the canonical names of interfaces classes used by
        dependencies (example: flt.agents.hapi.interface.IServerFactory).
        '''
        hostdef = kwargs.pop('hostdef', None)
        ip = kwargs.pop('ip', None)
        hostname = kwargs.pop('hostname', None)
        start_host = kwargs.pop('start_host', True)
        disable_monitoring = kwargs.pop('disable_monitoring', True)
        if kwargs:
            raise AttributeError("Unexpected kwargs argument %r" % (kwargs, ))

        ag = agency.Agency()
        ag.set_host_def(hostdef)
        self._agencies.append(ag)
        for canonical_name in components:
            comp = reflect.named_object(canonical_name)
            ag.set_mode(comp, ExecMode.production)

        tun_backend = tunneling.EmuBackend(version=self._tunneling_version,
                                           bridge=self._tunneling_bridge)
        if disable_monitoring:
            ag.disable_protocol('setup-monitoring', 'Task')

        counter = getattr(self, '_agency_counter', -1)
        self._agency_counter = counter + 1
        queue_name = "agency_%d" % (self._agency_counter, )
        msg = rabbitmq.Client(self._messaging, queue_name)
        tun = tunneling.Tunneling(tun_backend)

        d = ag.initiate(self._database, self._journaler, self, ip, hostname,
                        start_host, msg, tun)
        d.addCallback(defer.override_result, ag)
        d.addCallback(defer.bridge_param, self.wait_for_idle)
        return d

    @manhole.expose()
    def wait_for_idle(self, timeout=20, freq=0.01):
        return time.wait_for_ex(self.is_idle, timeout, freq, logger=self)

    @manhole.expose()
    def uuid(self):
        '''
        Generates random string.
        '''
        return str(uuid.uuid1())

    @manhole.expose()
    def descriptor_factory(self, type_name, shard=u'lobby', **kwargs):
        """
        Creates and returns a descriptor to pass it later
        for starting the agent.
        First parameter is a type_name representing the descirptor.
        Second parameter is optional (default lobby). Usage:
        > descriptor_factory('shard_descriptor', 'some shard')
        """
        desc = factories.build(type_name, shard=unicode(shard), **kwargs)
        return self._database_connection.save_document(desc)

    @manhole.expose()
    def breakpoint(self, name):
        """
        Register the breakpoint of the name. Usage:
        > breakpoint('setup-done')

        The name should be used in a call of Driver.register_breakpoint(name)
        method, which returns the Deferred, which will be fired by this
        command.
        """
        if name not in self._breakpoints:
            self.warning("Reached breakpoint %s but found no "
                         "callback registered")
            return
        cb = self._breakpoints[name]
        cb.callback(None)
        return cb

    @manhole.expose()
    def find_agency(self, agent_id):
        """
        Returns the agency running the agent with agent_id or None.
        """

        def has_agent(agency):
            for agent in agency._agents:
                if agent._descriptor.doc_id == agent_id:
                    return True
            return False

        matching = filter(has_agent, self._agencies)
        if len(matching) > 0:
            self.debug('Find agency returns %dth agency.',
                       self._agencies.index(matching[0]))
            return matching[0]

    @manhole.expose()
    @defer.inlineCallbacks
    def find_agent(self, agent_id):
        """
        Return the medium class of the agent with agent_id if the one is
        running in simulation.
        """
        try:
            recp = IRecipient(agent_id)
            agent_id = recp.key
        except TypeError:
            pass
        agency = self.find_agency(agent_id)
        if agency:
            agent = yield agency.find_agent(agent_id)
            defer.returnValue(agent)

    @manhole.expose()
    def count_shard_kings(self):
        res = 0
        for medium in self.iter_agents():
            agent = medium.get_agent()
            if not isinstance(agent, shard_agent.ShardAgent):
                continue
            if agent.is_king():
                res += 1
        return res

    @manhole.expose()
    def validate_shards(self):
        error = False
        for medium in self.iter_agents():
            agent = medium.get_agent()
            if not isinstance(agent, shard_agent.ShardAgent):
                continue
            _, alloc = agent.list_resource()
            allocated = alloc['neighbours']
            part = len(agent.query_partners('neighbours'))
            if allocated != part:
                self.error("Shard Agent of shard %r has %d allocated "
                           "resource and %d partners",
                           medium._descriptor.shard, allocated, part)
                error = True
            if part < 3 and agent.is_peasant():
                self.error(
                    "Shard Agent of shard %r has only %d partners and "
                    "is not a king", medium._descriptor.shard, part)
                error = True
        if not error:
            self.info('All ok!')


class Driver(log.Logger, log.LogProxy, Commands):

    log_category = 'simulation-driver'

    def __init__(self, jourfile=None,
                 tunneling_version=None, tunneling_bridge=None):
        log_keeper = log.get_default() or log.FluLogKeeper()
        log.LogProxy.__init__(self, log_keeper)
        log.Logger.__init__(self, self)
        Commands.__init__(self)

        self._messaging = emu.RabbitMQ()
        self._tunneling_version = tunneling_version
        self._tunneling_bridge = tunneling_bridge or tunneling.Bridge()
        self._database = database.Database()
        jouropts = dict()
        if jourfile:
            jouropts['filename'] = jourfile
            jouropts['encoding'] = 'zip'
        self._jourwriter = journaler.SqliteWriter(self, **jouropts)
        self._journaler = journaler.Journaler()

        self._output = Output()
        self._parser = manhole.Parser(self, self._output, self,
                                      self.finished_processing)

        self._agencies = list()
        self._breakpoints = dict()

        self._dependency_references = list()

        # uuid replacement for host agents
        self._counter = 0

    def get_stats(self):
        res = dict(self._messaging.get_stats())
        res.update(dict(self._database.get_stats()))
        return res

    def initiate(self):
        self._database_connection = self._database.get_connection()
        d1 = tools.push_initial_data(self._database_connection)
        d2 = self._jourwriter.initiate()
        self._journaler.configure_with(self._jourwriter)
        return defer.DeferredList([d1, d2])

    def get_local(self, name):
        return self._parser.get_local(name)

    def set_local(self, name, value):
        self._parser.set_local(value, name)

    def count_agents(self, agent_type=None):
        return len([x for x in self.iter_agents(agent_type)])

    def find_dependency(self, **conditions):

        def match(ref, conditions):
            for key, value in conditions.items():
                if getattr(ref, key) != value:
                    return False
            return True

        def iter_dependecies():
            for medium in self.iter_agents():
                for x in medium.iter_dependency_references():
                    yield x

        index = conditions.pop('index', None)
        matching = [ref for ref in iter_dependecies()
                    if match(ref, conditions)]
        if not matching:
            return
        if len(matching) == 1 and index is None:
            index = 0
        if len(matching) > 1 and index is None:
            raise ValueError('Found %d dependecies matching, you should '
                             'specify more or pass index.', len(matching))
        return matching[index].instance

    def disable_rabbitmq(self):
        self._messaging.disable()

    def enable_rabbitmq(self):
        self._messaging.enable()

    def freeze_all(self):
        '''
        Stop all activity of the agents running.
        '''
        d = defer.succeed(None)
        for x in self.iter_agents():
            d.addCallback(defer.drop_param, x._cancel_long_running_protocols)
            d.addCallback(defer.drop_param, x._cancel_all_delayed_calls)
            d.addCallback(defer.drop_param, x._kill_all_protocols)
        return d

    def snapshot_all_agents(self):
        for medium in self.iter_agents():
            medium.check_if_should_snapshot(force=True)

    @defer.inlineCallbacks
    def destroy(self):
        '''
        Called from tearDown of simulation tests. Cleans up everything.
        '''
        defers = list()
        for x in self.iter_agents():
            defers.append(x.terminate_hard())
        yield defer.DeferredList(defers)
        yield self._journaler.close()
        del(self._journaler)
        del(self._jourwriter)
        del(self._messaging)
        del(self._tunneling_bridge)
        del(self._database)
        del(self._agencies)
        del(self._breakpoints)
        del(self._parser)
        del(self._output)

    def remove_agency(self, agency):
        self._agencies.remove(agency)

    def iter_agencies(self):
        return self._agencies.__iter__()

    def iter_agents(self, agent_type=None):
        for agency in self._agencies:
            for agent in agency._agents:
                if agent_type is None or \
                   agent.get_agent().descriptor_type == agent_type:
                    yield agent

    def is_idle(self):
        return (self._messaging.is_idle()
                and self._tunneling_bridge.is_idle()
                and self.are_agencies_idle())

    def are_agencies_idle(self):
        return all([agency.is_idle() for agency in self.iter_agencies()])

    def register_breakpoint(self, name):
        if name in self._breakpoints:
            raise RuntimeError("Breakpoint with name: %s already registered",
                               name)
        d = defer.Deferred()
        self._breakpoints[name] = d
        return d

    def get_additional_parser(self, cb=None):
        return manhole.Parser(self, self._output, self, cb)

    def process(self, script):
        self._parser.dataReceived(script)

    def finished_processing(self):
        '''Called when the protocol runs out of data to process'''

    def get_host_agent_id(self, agent_id):
        self._counter += 1
        return '%s_%s' % (agent_id, self._counter)

    # Delegation of IDatabase methods for tests

    @manhole.expose()
    def reload_document(self, doc):
        assert isinstance(doc, document.Document)
        return self._database_connection.reload_document(doc)

    @manhole.expose()
    def get_document(self, doc_id):
        return self._database_connection.get_document(doc_id)

    @manhole.expose()
    def save_document(self, doc):
        return self._database_connection.save_document(doc)

    @manhole.expose()
    def delete_document(self, doc):
        return self._database_connection.delete_document(doc)


class Output(StringIO.StringIO, object):
    """
    This class is given to parser as an output in unit tests,
    when there is no transport to write to.
    """
