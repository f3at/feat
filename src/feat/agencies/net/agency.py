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
import re
import socket
import sys

from twisted.internet import reactor
from twisted.spread import pb

from feat.agents.base.agent import registry_lookup
from feat.agents.base import recipient
from feat.agencies import agency, journaler
from feat.agencies.net import ssh, broker, database, options
from feat.agencies.net.broker import BrokerRole
from feat.agencies.messaging import net, tunneling, rabbitmq, unix
from feat.common import log, defer, time, error, run, signal
from feat.common import manhole, text_helper
from feat.process import standalone
from feat.process.base import ProcessState
from feat.gateway import gateway
from feat.utils import locate
from feat.web import security

from feat.interface.agent import IAgentFactory
from feat.interface.agency import ExecMode


GATEWAY_PORT_COUNT = 100
TUNNELING_PORT_COUNT = 100


class AgencyAgent(agency.AgencyAgent):

    @manhole.expose()
    def get_gateway_port(self):
        return self.agency.gateway_port


class Startup(agency.Startup):

    def stage_configure(self):
        self.c = self.friend.config
        if self.c['agency']['daemonize']:
            os.chdir(self.c['agency']['rundir'])

        dbc = self.c['db']
        self._db = database.Database(dbc['host'],
                                     int(dbc['port']), dbc['name'])
        self._journaler = journaler.Journaler(self)

    def stage_private(self):
        reactor.addSystemEventTrigger('before', 'shutdown',
                                      self.friend.on_killed)

        mc = self.c['manhole']
        ssh_port = int(mc["port"]) if mc["port"] is not None else None

        self.friend._ssh = ssh.ListeningPort(self.friend,
                                      ssh.commands_factory(self.friend),
                                      public_key=mc["public_key"],
                                      private_key=mc["private_key"],
                                      authorized_keys=mc["authorized_keys"],
                                      port=ssh_port)

        socket_path = self.c['agency']['socket_path']
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
            d.addBoth(defer.drop_param, reactor.stop)
        return d


class Agency(agency.Agency):

    agency_agent_factory = AgencyAgent

    broker_factory = broker.Broker

    shutdown_factory = Shutdown
    startup_factory = Startup

    start_host_agent = True

    @classmethod
    def from_config(cls, env, options=None):
        agency = cls()
        agency._load_config(env, options)
        return agency

    def __init__(self,
                 msg_host=options.DEFAULT_MSG_HOST,
                 msg_port=options.DEFAULT_MSG_PORT,
                 msg_user=options.DEFAULT_MSG_USER,
                 msg_password=options.DEFAULT_MSG_PASSWORD,
                 db_host=options.DEFAULT_DB_HOST,
                 db_port=options.DEFAULT_DB_PORT,
                 db_name=options.DEFAULT_DB_NAME,
                 public_key=options.DEFAULT_MH_PUBKEY,
                 private_key=options.DEFAULT_MH_PRIVKEY,
                 authorized_keys=options.DEFAULT_MH_AUTH,
                 manhole_port=options.DEFAULT_MH_PORT,
                 agency_journal=options.DEFAULT_JOURFILE,
                 socket_path=options.DEFAULT_SOCKET_PATH,
                 lock_path=options.DEFAULT_LOCK_PATH,
                 gateway_port=options.DEFAULT_GW_PORT,
                 gateway_p12=options.DEFAULT_GW_P12_FILE,
                 allow_tcp_gateway=options.DEFAULT_ALLOW_TCP_GATEWAY,
                 tunneling_host=None,
                 tunneling_port=options.DEFAULT_TUNNEL_PORT,
                 tunneling_p12=options.DEFAULT_TUNNEL_P12_FILE,
                 enable_spawning_slave=options.DEFAULT_ENABLE_SPAWNING_SLAVE,
                 rundir=None,
                 logdir=None,
                 daemonize=options.DEFAULT_DAEMONIZE,
                 force_host_restart=options.DEFAULT_FORCE_HOST_RESTART):

        agency.Agency.__init__(self)

        curdir = os.path.abspath(os.curdir)
        if rundir is None:
            rundir = options.DEFAULT_RUNDIR if daemonize else curdir
        if logdir is None:
            logdir = options.DEFAULT_LOGDIR if daemonize else curdir

        self._init_config(msg_host=msg_host,
                          msg_port=msg_port,
                          msg_password=msg_password,
                          msg_user=msg_user,
                          db_host=db_host,
                          db_port=db_port,
                          db_name=db_name,
                          public_key=public_key,
                          private_key=private_key,
                          authorized_keys=authorized_keys,
                          manhole_port=manhole_port,
                          agency_journal=agency_journal,
                          socket_path=socket_path,
                          lock_path=lock_path,
                          gateway_port=gateway_port,
                          gateway_p12=gateway_p12,
                          allow_tcp_gateway=allow_tcp_gateway,
                          tunneling_port=tunneling_port,
                          tunneling_p12=tunneling_p12,
                          enable_spawning_slave=enable_spawning_slave,
                          rundir=rundir,
                          logdir=logdir,
                          daemonize=daemonize,
                          force_host_restart=force_host_restart)

        self._ssh = None
        self._broker = None
        self._gateway = None
        self._snapshot_task = None

        # this is default mode for the dependency modules
        self._set_default_mode(ExecMode.production)

    def wait_event(self, agent_id, event):
        return self._broker.wait_event(agent_id, event)

    ### public ###

    @property
    def role(self):
        return self._broker.state

    def locate_master(self):
        return (self.get_hostname(), self.config["gateway"]["port"],
                self._broker.state != BrokerRole.master)

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
        filename = os.path.join(self.config['agency']['logdir'],
                                self.config['agency']['journal'])
        self._journal_writer = journaler.SqliteWriter(
            self, filename=filename, encoding='zip',
            on_rotate=self._force_snapshot_agents)
        self._journaler.configure_with(self._journal_writer)
        self._journal_writer.initiate()
        self._start_master_gateway()

        self._redirect_text_log()
        self._create_pid_file()
        self._link_log_file(options.MASTER_LOG_LINK)

        signal.signal(signal.SIGUSR1, self._sigusr1_handler)
        signal.signal(signal.SIGUSR2, self._sigusr2_handler)

        if 'enable_host_restart' not in self._broker.shared_state:
            value = self.config['agency']['force_host_restart']
            self._broker.shared_state['enable_host_restart'] = value

        backends = []
        backends.append(self._initiate_messaging(self.config['msg']))
        backends.append(self._initiate_tunneling(self.config['tunnel']))
        backends.append(unix.Master(self._broker))
        backends = filter(None, backends)

        d = defer.succeed(None)
        for backend in backends:
            d.addCallback(defer.drop_param,
                          self._messaging.add_backend, backend)

        if self.config['agency']['enable_spawning_slave']:
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
        self._journal_writer = journaler.BrokerProxyWriter(self._broker)
        self._journaler.configure_with(self._journal_writer)
        self._journal_writer.initiate()
        self._redirect_text_log()
        self._start_slave_gateway()

        backend = unix.Slave(self._broker)
        return self._messaging.add_backend(backend)

    def is_idle(self):
        if agency.Agency.is_idle(self):
            return self._broker.is_idle()
        return False

    def _redirect_text_log(self):
        if self.config['agency']['daemonize']:
            log_id = str(self.agency_id)

            logname = "%s.%s.log" % ('feat', log_id, )
            logfile = os.path.join(self.config['agency']['logdir'], logname)
            log.FluLogKeeper.move_files(logfile, logfile)

    def _link_log_file(self, filename):
        if not self.config['agency']['daemonize']:
            return

        logfile, _ = log.FluLogKeeper.get_filenames()
        basedir = os.path.dirname(logfile)
        linkname = os.path.join(basedir, filename)
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
        self.full_kill(stop_process=True)

    def _sigusr2_handler(self, _signum, _frame):
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
            d.addCallback(defer.drop_param, run.delete_pidfile,
                          self.config['agency']['rundir'], force=True)
        return d

    def get_journal_writer(self):
        '''Called by the broker internals to establish the bridge between
        JournalWriters'''
        return self._journal_writer

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
        return self._shutdown(stop_process=stop_process, gentle=True)

    @manhole.expose()
    def kill(self, stop_process=False):
        return self._shutdown(stop_process=stop_process, gentle=False)

    def upgrade(self, upgrade_cmd, testing=False):
        return self._shutdown(full_shutdown=True, stop_process=not testing,
                              upgrade_cmd=upgrade_cmd, gentle=True)

    def _disconnect(self):
        d = defer.succeed(None)
        if self._ssh:
            d.addCallback(defer.drop_param, self._ssh.stop_listening)
        if self._gateway:
            d.addCallback(defer.drop_param, self._gateway.cleanup)
        if self._journaler:
            d.addCallback(defer.drop_param, self._journaler.close)
        if self._broker:
            d.addCallback(defer.drop_param, self._broker.disconnect)
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
            registry_lookup(descriptor.document_type))
        if factory.standalone:
            return self.start_standalone_agent(descriptor, factory, **kwargs)
        else:
            return self.start_agent_locally(descriptor, **kwargs)

    def start_agent_locally(self, descriptor, **kwargs):
        return agency.Agency.start_agent(self, descriptor, **kwargs)

    def start_standalone_agent(self, descriptor, factory, **kwargs):
        cmd, cmd_args, env = factory.get_cmd_line(descriptor, **kwargs)
        self._store_config(env)
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
        elif isinstance(found, pb.RemoteReference):
            host = self.get_hostname()
            port = yield found.callRemote('get_gateway_port')
            defer.returnValue((host, port, True, ))
        else: # None
            db = self._database.get_connection()
            host = yield locate.locate(db, agent_id)
            port = self.config["gateway"]["port"]
            if host is None:
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

    ### Manhole inspection methods ###

    @manhole.expose()
    def get_gateway_port(self):
        return self._gateway and self._gateway.port

    gateway_port = property(get_gateway_port)

    @manhole.expose()
    def find_agent_locally(self, agent_id):
        '''Same as find_agent but only checks in scope of this agency.'''
        return agency.Agency.find_agent(self, agent_id)

    @manhole.expose()
    def find_agent(self, agent_id):
        '''Gives medium class or its pb refrence of the agent if this agency
        hosts it.'''
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

    # Config manipulation (standalone agencies receive the configuration
    # in the environment).

    def _init_config(self,
                     msg_host=None,
                     msg_port=None,
                     msg_user=None,
                     msg_password=None,
                     db_host=None,
                     db_port=None,
                     db_name=None,
                     public_key=None,
                     private_key=None,
                     authorized_keys=None,
                     manhole_port=None,
                     agency_journal=None,
                     socket_path=None,
                     lock_path=None,
                     gateway_port=None,
                     gateway_p12=None,
                     allow_tcp_gateway=None,
                     tunneling_host=None,
                     tunneling_port=None,
                     tunneling_p12=None,
                     enable_spawning_slave=None,
                     rundir=None,
                     logdir=None,
                     daemonize=None,
                     force_host_restart=None):

        msg_conf = dict(host=msg_host,
                        port=msg_port,
                        user=msg_user,
                        password=msg_password)

        db_conf = dict(host=db_host,
                       port=db_port,
                       name=db_name)

        manhole_conf = dict(public_key=public_key,
                            private_key=private_key,
                            authorized_keys=authorized_keys,
                            port=manhole_port)

        for path in [socket_path, lock_path]:
            if path and not os.path.isabs(path):
                path = os.path.join(rundir, path)

        agency_conf = dict(journal=agency_journal,
                           socket_path=socket_path,
                           lock_path=lock_path,
                           rundir=rundir,
                           logdir=logdir,
                           enable_spawning_slave=enable_spawning_slave,
                           daemonize=daemonize,
                           force_host_restart=force_host_restart)
        gateway_conf = dict(port=gateway_port,
                            p12=gateway_p12,
                            allow_tcp=allow_tcp_gateway)

        if tunneling_host is None:
            tunneling_host = socket.gethostbyaddr(socket.gethostname())[0]

        tunnel_conf = dict(host=tunneling_host,
                           port=tunneling_port,
                           p12=tunneling_p12)

        self.config = dict()
        self.config['msg'] = msg_conf
        self.config['db'] = db_conf
        self.config['manhole'] = manhole_conf
        self.config['agency'] = agency_conf
        self.config['gateway'] = gateway_conf
        self.config['tunnel'] = tunnel_conf

    def _store_config(self, env):
        '''
        Stores agency config into environment to be read by the
        standalone agency.'''
        for key in self.config:
            for kkey in self.config[key]:
                var_name = "FEAT_%s_%s" % (key.upper(), kkey.upper(), )
                env[var_name] = str(self.config[key][kkey])

    def _load_config(self, env, options=None):
        '''
        Loads config from environment.
        Environment values can be overridden by specified options.
        '''
        # First load from env
        matcher = re.compile('\AFEAT_([^_]+)_(.+)\Z')
        for key in env:
            res = matcher.search(key)
            if res:
                c_key = res.group(1).lower()
                c_kkey = res.group(2).lower()
                value = str(env[key])
                if value == 'None':
                    value = None
                if value == 'False':
                    value = False
                if value == 'True':
                    value = True
                if c_key in self.config:
                    self.log("Setting %s.%s to %r", c_key, c_kkey, value)
                    self.config[c_key][c_kkey] = value

        #Then override with options
        if options:
            for group_key, conf_group in self.config.items():
                for conf_key in conf_group:
                    attr = "%s_%s" % (group_key, conf_key)
                    if hasattr(options, attr):
                        new_value = getattr(options, attr)
                        old_value = conf_group[conf_key]
                        if new_value is not None and (old_value != new_value):
                            if old_value is None:
                                self.log("Setting %s.%s to %r",
                                         group_key, conf_key, new_value)
                            else:
                                self.log("Overriding %s.%s to %r",
                                         group_key, conf_key, new_value)
                            conf_group[conf_key] = new_value

    def _initiate_messaging(self, config):
        try:
            host = config['host']
            port = int(config['port'])
            username = config['user']
            password = config['password']

            self.info("Setting up messaging using %s@%s:%d", username,
                      host, port)

            backend = net.RabbitMQ(host, port, username, password)
            backend.redirect_log(self)
            client = rabbitmq.Client(backend, self.get_hostname())
            return client
        except Exception as e:
            msg = "Failed to setup messaging backend"
            error.handle_exception(self, e, msg)
            # For now we do not support not having messaging backend
            raise

    def _initiate_tunneling(self, config):
        try:
            host = config["host"]
            port = int(config["port"])
            p12 = config["p12"]
            port_range = range(port, port + TUNNELING_PORT_COUNT)

            self.info("Setting up tunneling on %s ports %d-%d "
                      "using PKCS12 %r", host, port_range[0],
                      port_range[-1], p12)

            csec = security.ClientContextFactory(p12_filename=p12,
                                                 verify_ca_from_p12=True)
            cpol = security.ClientPolicy(csec)
            ssec = security.ServerContextFactory(p12_filename=p12,
                                                 verify_ca_from_p12=True)
            spol = security.ServerPolicy(ssec)
            backend = tunneling.Backend(host, port_range,
                                        client_security_policy=cpol,
                                        server_security_policy=spol)
            backend.redirect_log(self)
            frontend = tunneling.Tunneling(backend)
            return frontend

        except Exception as e:
            msg = "Failed to setup tunneling backend"
            error.handle_exception(self, e, msg)
        return None

    def _can_start_host_agent(self, startup=False):
        if self.role != BrokerRole.master:
            self.log('Not starting host agent, because we are not the '
                     'master agency')
            return False
        return agency.Agency._can_start_host_agent(self, startup)

    def _host_agent_restart_enabled(self):
        return self._broker.shared_state['enable_host_restart']

    def _on_host_started(self):
        self._broker.shared_state['enable_host_restart'] = True

    @defer.inlineCallbacks
    def _find_agent(self, agent_id):
        '''
        Specific to master agency, called by the broker.
        Will return AgencyAgent if agent is hosted by master agency,
        PB.Reference if it runs in stanadlone or None if it was not found.
        '''
        local = yield self.find_agent_locally(agent_id)
        if local:
            defer.returnValue(local)
        for slave in self._broker.iter_slaves():
            found = yield slave.callRemote('find_agent_locally', agent_id)
            if found:
                defer.returnValue(found)
        defer.returnValue(None)

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

    def _cancel_snapshoter(self):
        if self._snapshot_task is not None and self._snapshot_task.active():
            self._snapshot_task.cancel()
        self._snapshot_task = None

    def _create_gateway(self, config):
        try:
            port = int(config["port"])
            p12 = config["p12"]
            allow_tcp = config["allow_tcp"]
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
                                                    verify_ca_from_p12=True)
                sec = security.ServerPolicy(fac)
                self.info("Setting up SSL gateway on ports %d-%d "
                          "using PKCS12 %r", range[0], range[-1], p12)

            return gateway.Gateway(self, range, security_policy=sec)
        except Exception as e:
            error.handle_exception(self, e, "Failed to setup gateway")

    def _start_slave_gateway(self):
        self._gateway = self._create_gateway(self.config["gateway"])
        if self._gateway:
            self._gateway.initiate_slave()

    def _start_master_gateway(self):
        self._gateway = self._create_gateway(self.config["gateway"])
        if self._gateway:
            self._gateway.initiate_master()

    def _create_pid_file(self):
        rundir = self.config['agency']['rundir']
        pid_file = run.acquire_pidfile(rundir)

        path = run.write_pidfile(rundir, file=pid_file)
        self.log("Written pid file %s" % path)

    def _spawn_agency(self, desc="", args=[]):

        def get_cmd_line():
            python_path = ":".join(sys.path)
            path = os.environ.get("PATH", "")
            feat_debug = self.get_logging_filter()

            command = 'feat'
            args.append('-D')
            env = dict(PYTHONPATH=python_path,
                       FEAT_DEBUG=feat_debug,
                       PATH=path)
            return command, args, env

        if self._shutdown_task is not None:
            return

        self.log("Spawning %s agency", desc)
        cmd, cmd_args, env = get_cmd_line()
        self._store_config(env)

        p = standalone.Process(self, cmd, cmd_args, env)
        return p.restart()

    def _spawn_backup_agency(self):
        if self._broker.is_master() and not self._broker.has_slave():
            return self._spawn_agency("backup")

    def get_broker_backend(self):
        if self.role != broker.BrokerRole.master:
            raise RuntimeError("We are not a master, wtf?!")
        return self._messaging.get_backend('unix')
