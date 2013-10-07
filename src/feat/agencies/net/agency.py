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
import os
import sys

from twisted.internet import reactor, error as ierror

from feat.agencies import agency, journaler, recipient
from feat.agencies.net import ssh, broker, options, config
from feat.agencies.net.broker import BrokerRole
from feat.agencies.messaging import net, tunneling, rabbitmq, unix
from feat.database import driver
from feat.agents.base import replay

from feat.configure import configure
from feat import applications
from feat.common import log, defer, time, error, run, signal
from feat.common import manhole, text_helper, serialization

from feat.process import standalone
from feat.process.base import ProcessState
from feat.gateway import gateway
from feat.web import security

from feat.interface.agent import IAgentFactory
from feat.interface.agency import ExecMode
from feat.agencies.interface import AgencyRoles


GATEWAY_PORT_COUNT = 100
TUNNELING_PORT_COUNT = 100


class AgencyAgent(agency.AgencyAgent):

    @manhole.expose()
    def get_gateway_port(self):
        return self.agency.gateway_port

    @replay.named_side_effect('AgencyAgent.get_base_gateway_url')
    def get_base_gateway_url(self):
        return self.agency.gateway_base_url


class Startup(agency.Startup):

    def stage_configure(self):
        self.c = self.friend.config
        if self.c.agency.daemonize:
            os.chdir(self.c.agency.rundir)

        dbc = self.c.db
        assert isinstance(dbc, config.DbConfig), str(type(dbc))
        self._db = driver.Database(dbc.host, int(dbc.port), dbc.name,
                                   dbc.username, dbc.password,
                                   https=dbc.https)
        self._journaler = journaler.Journaler(
            on_rotate_cb=self.friend._force_snapshot_agents,
            on_switch_writer_cb=self.friend._on_journal_writer_switch,
            hostname=self.friend.get_hostname())
        # add the journaler to the LogTee which is the default keeper
        # dump the buffer with entries so far and remove it from the tee
        # at this point in future if we decide not to log to text files
        # we should remove the 'flulog' keeper from the tee as well
        tee = log.get_default()
        # FIXME: get_keeper is not an ILogWhatever method, only Tee has it
        try:
            buff = tee.get_keeper('buffer')
            buff.dump(self._journaler)
            buff.clean()
            tee.remove_keeper('buffer')
            tee.add_keeper('journaler', self._journaler)
        except AttributeError:
            self.warning('Programmer error, interface disrespect')

    def stage_private(self):
        reactor.addSystemEventTrigger('before', 'shutdown',
                                      self.friend.on_killed)

        mc = self.c.manhole
        assert isinstance(mc, config.ManholeConfig), str(type(mc))
        ssh_port = int(mc.port) if mc.port is not None else None

        self.friend._ssh = ssh.ListeningPort(self.friend,
                                      ssh.commands_factory(self.friend),
                                      public_key=mc.public_key,
                                      private_key=mc.private_key,
                                      authorized_keys=mc.authorized_keys,
                                      port=ssh_port)

        socket_path = self.c.agency.socket_path
        self.friend._broker = self.friend.broker_factory(self.friend,
                socket_path, on_master_cb=self.friend.on_become_master,
                on_slave_cb=self.friend.on_become_slave,
                on_disconnected_cb=self.friend.on_broker_disconnect,
                on_remove_slave_cb=self.friend.on_remove_slave,
                on_master_missing_cb=self.friend.on_master_missing)

        self.friend._setup_snapshoter()
        return self.friend._broker.initiate_broker()


class Shutdown(agency.Shutdown):

    def stage_slaves(self):
        if self.friend._broker is None:
            self.warning("Broker was not initialized yet and its shutdown "
                         "will be skipped")
            return
        if self.opts.get('full_shutdown', False):
            gentle = self.opts.get('gentle', False)
            return self.friend._broker.shutdown_slaves(gentle=gentle)

    def stage_agents(self):
        self.friend._cancel_snapshoter()

    def stage_internals(self):
        tee = log.get_default()
        try:
            tee.remove_keeper('journaler')
        except KeyError:
            pass
        return self.friend._disconnect()

    def stage_process(self):
        d = defer.succeed(None)

        u_cmd = self.opts.get('upgrade_cmd', None)
        if u_cmd is not None:
            args = u_cmd.split(" ")
            command = args.pop(0)
            process = standalone.Process(self.friend, command, args,
                                         os.environ.copy())

            d = process.restart()
            d.addBoth(defer.drop_param, process.wait_for_state,
                      ProcessState.finished, ProcessState.failed)

        if self.opts.get('stop_process', False):
            d.addBoth(defer.drop_param, self._stop_reactor)
        return d

    def _stop_reactor(self):
        if reactor.running:
            try:
                reactor.stop()
            except ierror.ReactorNotRunning:
                self.info("Swallowing ReactorNotRunning exception, "
                          " this is normal for the shutdown "
                          "triggered by SIGTERM.")


class Agency(agency.Agency):

    agency_agent_factory = AgencyAgent

    broker_factory = broker.Broker

    shutdown_factory = Shutdown
    startup_factory = Startup

    start_host_agent = True

    def __init__(self, config):
        agency.Agency.__init__(self)
        self.config = config
        self._hostname = unicode(self.config.agency.full_hostname)

        self._ssh = None
        self._broker = None
        self._gateway = None
        self._snapshot_task = None

        # this is default mode for the dependency modules
        self._set_default_mode(ExecMode.production)

    def wait_event(self, agent_id, event):
        return self._broker.wait_event(agent_id, event)

    ### public ###

    def initiate(self, **opts):
        d = super(Agency, self).initiate(*opts)
        d.addCallbacks(self._initiate_success, self._initiate_failure)
        return d

    @property
    def role(self):
        if self._broker.is_standalone():
            return AgencyRoles.standalone
        if self._broker.is_master():
            return AgencyRoles.master
        if self._broker.is_slave():
            return AgencyRoles.slave
        return AgencyRoles.unknown

    def locate_master(self):

        def pack_result(agency_id, is_remote):
            if not agency_id:
                return None
            return (self.get_hostname(),
                    self.config.gateway.port,
                    self.agency_id, is_remote)

        if self._broker.is_master():
            d = defer.succeed(self.agency_id)
            d.addCallback(pack_result, False)
        else:
            d = self._broker.fetch_master_id()
            d.addCallback(pack_result, True)
        return d

    def locate_agency(self, agency_id):

        def pack_result(port, remote):
            return self.get_hostname(), port, remote

        if agency_id == self.agency_id:
            return defer.succeed(pack_result(self.gateway_port, False))

        for slave_id, slave in self._broker.slaves.iteritems():
            if slave_id == agency_id:
                d = slave.callRemote('get_gateway_port')
                d.addCallback(pack_result, True)
                return d

        return defer.succeed(None)

    def on_become_master(self):
        self._ssh.start_listening()
        self._journaler.set_connection_strings(self.config.agency.journal)
        try:
            self._start_master_gateway()
        except Exception as e:
            error.handle_exception(
                self, e, "Failed setting up gateway, it will stay disabled.")

        self._create_pid_file()
        self.link_log_file(options.MASTER_LOG_LINK)

        signal.signal(signal.SIGUSR1, self._sigusr1_handler)
        signal.signal(signal.SIGUSR2, self._sigusr2_handler)

        backends = []
        backends.append(self._initiate_messaging(self.config.msg))
        backends.append(self._initiate_tunneling(self.config.tunnel))
        backends.append(unix.Master(self._broker))
        backends = filter(None, backends)

        d = defer.succeed(None)
        for backend in backends:
            d.addCallback(defer.drop_param,
                          self._messaging.add_backend, backend)

        if (self.config.agency.enable_spawning_slave
            and sys.platform != "win32"):
            d.addCallback(defer.drop_param, self._spawn_backup_agency)

        d.addCallback(defer.drop_param, self._start_host_agent)
        return d

    def on_remove_slave(self):
        return self._spawn_backup_agency()

    def on_master_missing(self):
        pass

    def on_become_slave(self):
        self.start_host_agent = False
        self._ssh.stop_listening()
        writer = journaler.BrokerProxyWriter(self._broker)
        writer.initiate()
        self._journaler.configure_with(writer)
        self._start_slave_gateway()

        backend = unix.Slave(self._broker)
        return self._messaging.add_backend(backend)

    def is_idle(self):
        if agency.Agency.is_idle(self):
            return self._broker.is_idle()
        return False

    def _initiate_success(self, _value):
        self.info("Agency initiate finished successfully")

        # this initiates startup of HA in a broken execution thread,
        # so there is no need to return/yield the return value
        self._start_host_agent()

    def _initiate_failure(self, fail):
        error.handle_failure(self, fail, 'Agency initiate failed, exiting.')
        self.kill(stop_process=True)
        return fail

    def link_log_file(self, filename):
        if not self.config.agency.daemonize:
            # if haven't demonized the log is just at the users console
            return

        logfile, _ = log.FluLogKeeper.get_filenames()
        linkname = os.path.join(self.config.agency.logdir, filename)
        try:
            os.unlink(linkname)
        except OSError:
            pass
        try:
            os.symlink(logfile, linkname)
        except OSError as e:
            self.warning("Failed to link log file %s to %s: %s",
                         logfile, linkname, error.get_exception_message(e))

    def _sigusr1_handler(self, _signum, _frame):
        self.info("Process received signal USR1")
        self.full_kill(stop_process=True)

    def _sigusr2_handler(self, _signum, _frame):
        self.info("Process received signal USR2")
        self.full_shutdown(stop_process=True)

    def on_broker_disconnect(self, pre_state):
        try:
            signal.unregister(signal.SIGUSR1, self._sigusr1_handler)
        except ValueError:
            # this is expected result in case of slave agencies
            pass

        self._messaging.remove_backend('unix')

        self._ssh.stop_listening()
        d = self._journaler.close(flush_writer=False)
        if self._gateway:
            d.addCallback(defer.drop_param, self._gateway.cleanup)

        if pre_state == BrokerRole.master:
            self.debug('Removing pid file.')
            d.addCallback(defer.drop_param, run.delete_pidfile,
                          self.config.agency.rundir, force=True)
        return d

    def remote_get_journaler(self):
        '''Called by the broker internals to establish the bridge between
        JournalWriters'''
        return self._journaler

    def on_killed(self):
        return self._shutdown(stop_process=False, gentle=False)

    @manhole.expose()
    def full_shutdown(self, stop_process=False):
        '''Terminate all the slave agencies and shutdowns itself.'''
        return self._shutdown(full_shutdown=True, stop_process=stop_process,
                              gentle=True)

    @manhole.expose()
    def full_kill(self, stop_process=False):
        '''
        Terminate all the slave agencies without shutting down the agents.
        '''
        return self._shutdown(full_shutdown=True, stop_process=stop_process,
                              gentle=False)

    @manhole.expose()
    def shutdown(self, stop_process=False):
        '''Shutdown the agency in gentel manner (terminate all the agents).'''
        self.info("Agency.shutdown() called.")
        return self._shutdown(stop_process=stop_process, gentle=True)

    @manhole.expose()
    def kill(self, stop_process=False):
        return self._shutdown(stop_process=stop_process, gentle=False)

    def upgrade(self, upgrade_cmd, testing=False):
        return self._shutdown(full_shutdown=True, stop_process=not testing,
                              upgrade_cmd=upgrade_cmd, gentle=True)

    def _disconnect(self):
        self.debug('In agent._disconnect(), '
                   'ssh: %r, gateway: %r, journaler: %r, '
                   'database: %r, broker: %r', self._ssh, self._gateway,
                   self._journaler, self._database, self._broker)
        d = defer.succeed(None)

        handler = lambda msg: (1, error.handle_failure, self, msg)
        if self._ssh:
            d.addCallback(defer.drop_param, self._ssh.stop_listening)
            d.addCallbacks(defer.drop_param, defer.inject_param,
                           callbackArgs=(self.debug, "SSH stopped"),
                           errbackArgs=handler("Failed stopping SSH"))
        if self._gateway:
            d.addCallback(defer.drop_param, self._gateway.cleanup)
            d.addCallbacks(defer.drop_param, defer.inject_param,
                           callbackArgs=(self.debug, "Gateway stopped"),
                           errbackArgs=handler("Failed stopping gateway"))
        if self._journaler:
            d.addCallback(defer.drop_param, self._journaler.close)
            d.addCallbacks(defer.drop_param, defer.inject_param,
                           callbackArgs=(self.debug, "Journaler closed"),
                           errbackArgs=handler("Failed closing journaler"))

        if self._database:
            d.addCallback(defer.drop_param, self._database.disconnect)
            d.addCallbacks(defer.drop_param, defer.inject_param,
                           callbackArgs=(self.debug, "Database disconnected"),
                           errbackArgs=handler("Failed disconnecting from "
                                               "the database"))
        if self._broker:
            d.addCallback(defer.drop_param, self._broker.disconnect)
            d.addCallbacks(defer.drop_param, defer.inject_param,
                           callbackArgs=(self.debug, "Broker disconnected"),
                           errbackArgs=handler("Failed disconnecting from "
                                               "the broker"))
        return d

    def register_agent(self, medium):
        agency.Agency.register_agent(self, medium)
        self._broker.register_agent(medium)

    def unregister_agent(self, medium):
        agency.Agency.unregister_agent(self, medium)
        agent_id = medium.get_agent_id()
        self._broker.push_event(agent_id, 'unregistered')
        self._broker.unregister_agent(medium)
        self._start_host_agent()

    @manhole.expose()
    @serialization.freeze_tag('IAgency.start_agent')
    def start_agent(self, descriptor, **kwargs):
        """
        Starting an agent is delegated to the broker, who makes sure that
        this method will be eventually run on the master agency.
        """
        return self._broker.start_agent(descriptor, **kwargs)

    def actually_start_agent(self, descriptor, **kwargs):
        """
        This method will be run only on the master agency.
        """
        factory = IAgentFactory(
            applications.lookup_agent(descriptor.type_name))
        if factory.standalone:
            return self.start_standalone_agent(descriptor, factory, **kwargs)
        else:
            return self.start_agent_locally(descriptor, **kwargs)

    def start_standalone_agent(self, descriptor, factory, **kwargs):
        if sys.platform == "win32":
            raise NotImplementedError("Standalone agent are not supported "
                                      "on win32 platform")
        cmd, cmd_args, env = factory.get_cmd_line(descriptor, **kwargs)
        self.config.store(env)
        recp = recipient.Agent(descriptor.doc_id, descriptor.shard)

        d = self._broker.wait_event(recp.key, 'started')
        d.addCallback(lambda _: recp)

        p = standalone.Process(self, cmd, cmd_args, env)
        p.restart()

        return d

    @manhole.expose()
    @defer.inlineCallbacks
    def locate_agent(self, recp):
        '''locate_agent(recp): Return (host, port, should_redirect) tuple.
        '''
        if recipient.IRecipient.providedBy(recp):
            agent_id = recp.key
        else:
            agent_id = recp
        found = yield self.find_agent(agent_id)
        if isinstance(found, agency.AgencyAgent):
            host = self.get_hostname()
            port = self.gateway_port
            defer.returnValue((host, port, False, ))
        elif isinstance(found, broker.AgentReference):
            host = self.get_hostname()
            port = yield found.reference.callRemote('get_gateway_port')
            defer.returnValue((host, port, True, ))
        else: # None
            # lazy import not to load descriptor before feat is loaded
            from feat.utils import locate
            db = self._database.get_connection()
            host = yield locate.locate(db, agent_id)
            port = self.config.gateway.port
            if host is None or (self._broker.is_master() and
                                host == self.get_hostname()):
                # Second condition reflects the situation when the agent
                # has its descriptor in the database but is not running.
                # It breaks the infinite redirect loop.
                defer.returnValue(None)
            else:
                defer.returnValue((host, port, True, ))

    @manhole.expose()
    def reconfigure_messaging(self, msg_host, msg_port):
        '''force messaging reconnector to the connect to the (host, port)'''
        self._messaging.create_external_route(
            'rabbitmq', host=msg_host, port=msg_port)

    @manhole.expose()
    def reconfigure_database(self, host, port, name='feat'):
        '''force database reconnector to connect to the (host, port, name)'''
        self._database.reconfigure(host, port, name)

    @manhole.expose()
    def show_connections(self):
        t = text_helper.Table(
            fields=("Connection", "Connected", "Host", "Port", "Reconnect in"),
            lengths=(20, 15, 30, 10, 15))
        connections = [self._database, self._messaging]
        iterator = (x.show_connection_status() for x in connections)
        return t.render(iterator)

    @manhole.expose()
    def show_locked_db_documents(self):
        return ("_document_locks: %r\n_pending_notifications: %r" %
                (self._database.show_document_locks()))

    ### Manhole inspection methods ###

    @manhole.expose()
    def get_gateway_port(self):
        return self._gateway and self._gateway.port

    @manhole.expose()
    def get_agency_id(self):
        return self.agency_id

    gateway_port = property(get_gateway_port)

    @property
    def gateway_base_url(self):
        if not self._gateway:
            raise error.FeatError(
                "How is it possible we don't have a gateway?")
        return self._gateway.base_url

    @manhole.expose()
    def find_agent_locally(self, agent_id):
        '''Same as find_agent but only checks in scope of this agency.'''
        return agency.Agency.find_agent(self, agent_id)

    @manhole.expose()
    def find_agent(self, agent_id):
        '''Gives medium class or its pb reference (wrapped in AgentReference
        object) of the agent if this agency hosts it.'''
        return self._broker.find_agent(agent_id)

    def iter_agency_ids(self):
        return self._broker.iter_agency_ids()

    @manhole.expose()
    @defer.inlineCallbacks
    def list_slaves(self):
        '''Print information about the slave agencies.'''
        resp = []
        for slave_id, slave in self._broker.slaves.iteritems():
            resp += ["#### Slave %s ####" % slave_id]
            table = yield slave.callRemote('list_agents')
            resp += [table]
            resp += []
        defer.returnValue("\n".join(resp))

    @manhole.expose()
    def get_slave(self, slave_id):
        '''Give the reference to the nth slave agency.'''
        return self._broker.slaves[slave_id].reference

    def _initiate_messaging(self, mconfig):
        assert isinstance(mconfig, config.MsgConfig), str(type(mconfig))
        try:
            host = mconfig.host
            port = int(mconfig.port)
            username = mconfig.user
            password = mconfig.password

            self.info("Setting up messaging using %s@%s:%d", username,
                      host, port)

            backend = net.RabbitMQ(host, port, username, password)
            client = rabbitmq.Client(backend, self.get_hostname())
            return client
        except Exception as e:
            msg = "Failed to setup messaging backend"
            error.handle_exception(self, e, msg)
            # For now we do not support not having messaging backend
            raise

    def _initiate_tunneling(self, tconfig):
        assert isinstance(tconfig, config.TunnelConfig), str(type(tconfig))
        try:
            host = tconfig.host
            port = int(tconfig.port)
            p12 = tconfig.p12
            port_range = range(port, port + TUNNELING_PORT_COUNT)

            self.info("Setting up tunneling on %s ports %d-%d "
                      "using PKCS12 %r", host, port_range[0],
                      port_range[-1], p12)

            csec = security.ClientContextFactory(p12_filename=p12,
                                                 verify_ca_from_p12=True)
            cpol = security.ClientPolicy(csec)
            ssec = security.ServerContextFactory(p12_filename=p12,
                                                 verify_ca_from_p12=True,
                                                 enforce_cert=True)
            spol = security.ServerPolicy(ssec)
            backend = tunneling.Backend(host, port_range,
                                        client_security_policy=cpol,
                                        server_security_policy=spol)
            frontend = tunneling.Tunneling(backend)
            return frontend

        except Exception as e:
            msg = "Failed to setup tunneling backend"
            error.handle_exception(self, e, msg)
        return None

    def _can_start_host_agent(self):
        if not self._broker.is_master():
            self.log('Not starting host agent, because we are not the '
                     'master agency')
            return False
        return agency.Agency._can_start_host_agent(self)

    @manhole.expose()
    def snapshot_agents(self, force=False):
        agency.Agency.snapshot_agents(self, force)
        if force:
            return self._broker.broadcast_force_snapshot()

    def _setup_snapshoter(self):
        self._snapshot_task = time.callLater(300, self._trigger_snapshot)

    def _trigger_snapshot(self):
        self.log("Snapshoting all the agents.")
        self.snapshot_agents()
        self._snapshot_task = None
        self._setup_snapshoter()

    def _force_snapshot_agents(self):
        self.log("Journal has been rotated, forcing snapshot of agents")
        # TODO: Mind also the agents running in slave agencies
        self.snapshot_agents(force=True)

    def _on_journal_writer_switch(self, current_index):
        if current_index == 0:
            method = self.resolve_alert
        else:
            method = self.raise_alert
        method("primary journaler")

    def _cancel_snapshoter(self):
        if self._snapshot_task is not None and self._snapshot_task.active():
            self._snapshot_task.cancel()
        self._snapshot_task = None

    def _create_gateway(self, gconfig):
        assert isinstance(gconfig, config.GatewayConfig), str(type(gconfig))
        try:
            port = int(gconfig.port)
            p12 = gconfig.p12
            allow_tcp = gconfig.allow_tcp
            range = (port, port + GATEWAY_PORT_COUNT)

            if not os.path.exists(p12):
                if not allow_tcp:
                    self.warning("No gateway PKCS12 specified or file "
                                 "not found, gateway disabled: %s", p12)
                    return
                sec = security.UnsecuredPolicy()
                self.info("Setting up TCP gateway on ports %d-%d",
                          range[0], range[-1])
            else:
                fac = security.ServerContextFactory(p12_filename=p12,
                                                    verify_ca_from_p12=True,
                                                    enforce_cert=True)
                sec = security.ServerPolicy(fac)
                self.info("Setting up SSL gateway on ports %d-%d "
                          "using PKCS12 %r", range[0], range[-1], p12)

            return gateway.Gateway(self, range, hostname=self.get_hostname(),
                                   security_policy=sec, log_keeper=self)
        except Exception as e:
            error.handle_exception(self, e, "Failed to setup gateway")

    def _start_slave_gateway(self):
        self._gateway = self._create_gateway(self.config.gateway)
        if self._gateway:
            self._gateway.initiate_slave()

    def _start_master_gateway(self):
        self._gateway = self._create_gateway(self.config.gateway)
        if self._gateway:
            self._gateway.initiate_master()

    def _create_pid_file(self):
        rundir = self.config.agency.rundir
        pid_file = run.acquire_pidfile(rundir)

        path = run.write_pidfile(rundir, file=pid_file)
        self.debug("Written pid file %s" % path)

    def _spawn_agency(self, desc="", args=[]):

        def get_cmd_line():
            python_path = ":".join(sys.path)
            path = os.environ.get("PATH", "")
            feat_debug = self.get_logging_filter()

            command = os.path.join(configure.bindir, 'feat')
            env = dict(PYTHONPATH=python_path,
                       FEAT_DEBUG=feat_debug,
                       PATH=path)
            return command, args, env

        if self._shutdown_task is not None:
            return

        self.log("Spawning %s agency", desc)
        cmd, cmd_args, env = get_cmd_line()
        self.config.store(env)

        p = standalone.Process(self, cmd, cmd_args, env)
        return p.restart()

    def _spawn_backup_agency(self):
        if self._broker.is_master() and not self._broker.has_slave():
            return self._spawn_agency("backup")

    def get_broker_backend(self):
        if not self._broker.is_master():
            raise RuntimeError("We are not a master, wtf?!")
        return self._messaging.get_backend('unix')

    ### IAgency ###

    @serialization.freeze_tag('IAgency.get_config')
    @replay.named_side_effect('IAgency.get_config')
    def get_config(self):
        return self.config
