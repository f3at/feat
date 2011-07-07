import optparse
import re
import types

from twisted.internet import reactor
from twisted.spread import pb

from feat.agents.base.agent import registry_lookup
from feat.agents.base import recipient, descriptor
from feat.agents.common import host
from feat.agencies import agency, journaler
from feat.agencies.net import ssh, broker
from feat.common import manhole, defer, time, text_helper, first
from feat.process import standalone
from feat.common.serialization import json
from feat.gateway import gateway
from feat.utils import locate

from feat.agencies.net import messaging
from feat.agencies.net import database

from feat.interface.agent import *
from feat.interface.agency import *
from feat.agencies.interface import *
from feat.agencies.net.broker import BrokerRole


DEFAULT_SOCKET_PATH = None # Use broker default
DEFAULT_MSG_HOST = "localhost"
DEFAULT_MSG_PORT = 5672
DEFAULT_MSG_USER = "guest"
DEFAULT_MSG_PASSWORD = "guest"
DEFAULT_DB_HOST = database.DEFAULT_DB_HOST
DEFAULT_DB_PORT = database.DEFAULT_DB_PORT
DEFAULT_DB_NAME = database.DEFAULT_DB_NAME
DEFAULT_JOURFILE = 'journal.sqlite3'
DEFAULT_GW_PORT = 5500

# Only for command-line options
DEFAULT_MH_PUBKEY = "public.key"
DEFAULT_MH_PRIVKEY = "private.key"
DEFAULT_MH_AUTH = "authorized_keys"
DEFAULT_MH_PORT = 6000


GATEWAY_PORT_COUNT = 100


def add_options(parser):
    # Agency related options
    group = optparse.OptionGroup(parser, "Agency options")
    group.add_option('-j', '--jourfile',
                     action="store", dest="agency_journal",
                     help=("journal filename (default: %s)"
                           % DEFAULT_JOURFILE),
                     default=DEFAULT_JOURFILE)
    group.add_option('-S', '--socket-path', dest="agency_socket_path",
                     help="path to the unix socket used by the agency",
                     metavar="PATH", default=DEFAULT_SOCKET_PATH)
    parser.add_option_group(group)

    # Messaging related options
    group = optparse.OptionGroup(parser, "Messaging options")
    group.add_option('-m', '--msghost', dest="msg_host",
                     help="host of messaging server to connect to",
                     metavar="HOST", default=DEFAULT_MSG_HOST)
    group.add_option('-p', '--msgport', dest="msg_port",
                     help="port of messaging server to connect to",
                     metavar="PORT", default=DEFAULT_MSG_PORT, type="int")
    group.add_option('-u', '--msguser', dest="msg_user",
                     help="username to loging to messaging server",
                     metavar="USER", default=DEFAULT_MSG_USER)
    group.add_option('-c', '--msgpass', dest="msg_password",
                     help="password to messaging server",
                     metavar="PASSWORD", default=DEFAULT_MSG_PASSWORD)
    parser.add_option_group(group)

    # database related options
    group = optparse.OptionGroup(parser, "Database options")
    group.add_option('-H', '--dbhost', dest="db_host",
                     help="host of database server to connect to",
                     metavar="HOST", default=DEFAULT_DB_HOST)
    group.add_option('-P', '--dbport', dest="db_port",
                     help="port of messaging server to connect to",
                     metavar="PORT", default=DEFAULT_DB_PORT, type="int")
    group.add_option('-N', '--dbname', dest="db_name",
                     help="host of database server to connect to",
                     metavar="NAME", default=DEFAULT_DB_NAME)
    parser.add_option_group(group)

    # manhole specific
    group = optparse.OptionGroup(parser, "Manhole options")
    group.add_option('-k', '--pubkey', dest='manhole_public_key',
                     help="public key used by the manhole",
                     default=DEFAULT_MH_PUBKEY)
    group.add_option('-K', '--privkey', dest='manhole_private_key',
                     help="private key used by the manhole",
                     default=DEFAULT_MH_PRIVKEY)
    group.add_option('-A', '--authorized', dest='manhole_authorized_keys',
                     help="file with authorized keys to be used by manhole",
                     default=DEFAULT_MH_AUTH)
    group.add_option('-M', '--manhole', type="int", dest='manhole_port',
                     help="port for the manhole to listen", metavar="PORT",
                     default=DEFAULT_MH_PORT)
    parser.add_option_group(group)

    # gateway specific
    group = optparse.OptionGroup(parser, "Gateway options")
    group.add_option('-w', '--gateway-port', type="int", dest='gateway_port',
                     help="port for the gateway to listen", metavar="PORT",
                     default=DEFAULT_GW_PORT)
    parser.add_option_group(group)


def check_options(opts, args):
    return opts, args


class AgencyAgent(agency.AgencyAgent):

    @manhole.expose()
    def get_gateway_port(self):
        return self.agency.gateway_port


class Agency(agency.Agency):

    agency_agent_factory = AgencyAgent

    @classmethod
    def from_config(cls, env, options=None):
        agency = cls()
        agency._load_config(env, options)
        return agency

    def __init__(self, msg_host=None, msg_port=None,
                 msg_user=None, msg_password=None,
                 db_host=None, db_port=None, db_name=None,
                 public_key=None, private_key=None,
                 authorized_keys=None, manhole_port=None,
                 agency_journal=None, socket_path=None,
                 gateway_port=None):
        agency.Agency.__init__(self)
        self._init_config(msg_host=msg_host,
                          msg_port=msg_port,
                          msg_password=msg_password,
                          db_host=db_host,
                          db_port=db_port,
                          db_name=db_name,
                          public_key=public_key,
                          private_key=private_key,
                          authorized_keys=authorized_keys,
                          manhole_port=manhole_port,
                          agency_journal=agency_journal,
                          socket_path=socket_path,
                          gateway_port=gateway_port)

        self._ssh = None
        self._broker = None
        self._gateway = None

        # this is default mode for the dependency modules
        self._set_default_mode(ExecMode.production)

        # hostdef to pass to the Host Agent we run
        self._hostdef = None

        # flag saying that we are in the process of starting the Host Agent,
        # it's used not to do this more than once
        self._starting_host = False
        # flag set when we enter the agency shutdown. It's used not to trigger
        # starting new host agent while we are shutting down the agency
        self._shutting_down = False
        # list of agent types or descriptors to spawn when the host agent
        # is ready. Format (agent_type_or_desc, args, kwargs)
        self._to_spawn = list()
        # semaphore preventing multiple entries into logic spawning agents
        # by host agent
        self._flushing_sem = defer.DeferredSemaphore(1)

    @manhole.expose()
    def spawn_agent(self, desc, *args, **kwargs):
        '''spawn_agent(agent_type_or_desc, *args, **kwargs) -> tells the host
        agent running in this agency to spawn a new agent of the given type.'''
        self._to_spawn.append((desc, args, kwargs, ))
        return self._flush_agents_to_spawn()

    def _flush_agents_to_spawn(self):
        return self._flushing_sem.run(self._flush_agents_body)

    @defer.inlineCallbacks
    def _flush_agents_body(self):
        medium = self._get_host_medium()
        if medium is None:
            msg = "Host Agent not ready yet, agent will be spawned later."
            defer.returnValue(msg)
        yield medium.wait_for_state(AgencyAgentState.ready)
        agent = medium.get_agent()
        while True:
            try:
                to_spawn = self._to_spawn.pop(0)
            except IndexError:
                break
            desc, args, kwargs = to_spawn
            if not isinstance(desc, descriptor.Descriptor):
                factory = descriptor.lookup(desc)
                if factory is None:
                    raise ValueError(
                        'No descriptor factory found for agent %r' % desc)
                desc = factory()
            desc = yield medium.save_document(desc)
            yield agent.start_agent(desc, **kwargs)

    def initiate(self):
        mesg = messaging.Messaging(
            self.config['msg']['host'], int(self.config['msg']['port']),
            self.config['msg']['user'], self.config['msg']['password'])
        db = database.Database(
            self.config['db']['host'], int(self.config['db']['port']),
            self.config['db']['name'])
        jour = journaler.Journaler(self)
        self._journal_writer = None

        reactor.addSystemEventTrigger('before', 'shutdown',
                                      self.on_killed)

        mc = self.config['manhole']
        ssh_port = int(mc["port"]) if mc["port"] is not None else None
        self._ssh = ssh.ListeningPort(self, ssh.Commands(self),
                                      public_key=mc["public_key"],
                                      private_key=mc["private_key"],
                                      authorized_keys=mc["authorized_keys"],
                                      port=ssh_port)

        socket_path = self.config['agency']['socket_path']
        self._broker = broker.Broker(self, socket_path,
                                on_master_cb=self.on_become_master,
                                on_slave_cb=self.on_become_slave,
                                on_disconnected_cb=self.on_broker_disconnect)

        self._setup_snapshoter()

        d = defer.succeed(None)
        d.addBoth(defer.drop_param, agency.Agency.initiate,
                  self, mesg, db, jour)
        d.addBoth(defer.drop_param, self._broker.initiate_broker)
        d.addBoth(defer.override_result, self)
        return d

    ### public ###

    def set_host_def(self, hostdef):
        '''
        Sets the hostdef param which will get passed to the Host Agent which
        the agency starts if it becomes the master.
        '''
        if not isinstance(hostdef,
                          (host.HostDef, unicode, str, types.NoneType)):
            raise AttributeError("Expected attribute 1 to be a HostDef or "
                                 "a document id got %r instead." %
                                 (hostdef, ))
        if self._hostdef is not None:
            self.info("Overwriting previous hostdef, which was %r",
                      self._hostdef)
        self._hostdef = hostdef

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
        self._journal_writer = journaler.SqliteWriter(
            self, filename=self.config['agency']['journal'], encoding='zip',
            on_rotate=self._force_snapshot_agents)
        self._journaler.configure_with(self._journal_writer)
        self._journal_writer.initiate()
        self._start_master_gateway()
        return self._start_host_agent_if_necessary()

    def on_become_slave(self):
        self._ssh.stop_listening()
        self._journal_writer = journaler.BrokerProxyWriter(self._broker)
        self._journaler.configure_with(self._journal_writer)
        self._journal_writer.initiate()
        self._start_slave_gateway()

    def on_broker_disconnect(self):
        self._ssh.stop_listening()
        if self._journal_writer:
            self._journal_writer.close()
            self._journal_writer = None
        self._journaler.close()

    def get_journal_writer(self):
        '''Called by the broker internals to establish the bridge between
        JournalWriters'''
        return self._journal_writer

    def on_killed(self):
        if self._journal_writer:
            self._journal_writer.close()
        d = agency.Agency.on_killed(self)
        d.addCallback(lambda _: self._disconnect)
        return d

    @manhole.expose()
    def full_shutdown(self):
        '''full_shutdown() -> Terminate all the slave agencies and shutdowns
        itself.'''
        d = self._broker.shutdown_slaves()
        d.addCallback(defer.drop_param, self.shutdown)
        return d

    @manhole.expose()
    def shutdown(self):
        '''shutdown() -> Shutdown the agency in gentel manner (terminating
        all the agents).'''
        self._shutting_down = True
        self._cancel_snapshoter()
        d = agency.Agency.shutdown(self)
        d.addCallback(defer.drop_param, self._disconnect)
        return d

    def upgrade(self, upgrade_cmd):
        d = agency.Agency.shutdown(self)
        #TODO: stop reactor and actually run the command (not part of the task)
        return d

    def _disconnect(self):
        d = defer.succeed(None)
        d.addCallback(defer.drop_param, self._ssh.stop_listening)
        d.addCallback(defer.drop_param, self._gateway.cleanup)
        d.addCallback(defer.drop_param, self._broker.disconnect)
        return d

    def unregister_agent(self, medium):
        agency.Agency.unregister_agent(self, medium)
        self._start_host_agent_if_necessary()

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
        cmd, cmd_args, env = factory.get_cmd_line(**kwargs)
        self._store_config(env)
        env['FEAT_AGENT_ID'] = str(descriptor.doc_id)
        env['FEAT_AGENT_KWARGS'] = json.serialize(kwargs)
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
        '''reconfigure_messaging(host, port) -> force messaging reconnector
        to the connect to the (host, port)'''
        self._messaging.reconfigure(msg_host, msg_port)

    @manhole.expose()
    def reconfigure_database(self, host, port, name='feat'):
        '''reconfigure_database(host, port, name=\'feat\') -> force database
        reconnector to connect to the (host, port, db_name)'''
        self._database.reconfigure(host, port, name)

    @manhole.expose()
    def show_connections(self):
        t = text_helper.Table(
            fields=("Connection", "Connected", "Host", "Port", "Reconnect in"),
            lengths=(20, 15, 30, 10, 15))

        iterator = (x.show_status()
                    for x in (self._messaging, self._database))
        return t.render(iterator)

    ### Manhole inspection methods ###

    @manhole.expose()
    def get_gateway_port(self):
        return self._gateway and self._gateway.port

    gateway_port = property(get_gateway_port)

    @manhole.expose()
    def find_agent_locally(self, agent_id):
        '''find_agent_locally(agent_id_or_descriptor) -> Same as find_agent
        but only checks in scope of this agency.'''
        return agency.Agency.find_agent(self, agent_id)

    @manhole.expose()
    def find_agent(self, agent_id):
        '''find_agent(agent_id_or_descriptor) -> Gives medium class or its
        pb refrence of the agent if this agency hosts it.'''
        return self._broker.find_agent(agent_id)

    def iter_agency_ids(self):
        return self._broker.iter_agency_ids()

    @manhole.expose()
    @defer.inlineCallbacks
    def list_slaves(self):
        '''list_slaves() -> Print information about the slave agencies.'''
        resp = []
        for slave_id, slave in self._broker.slaves.iteritems():
            resp += ["#### Slave %s ####" % slave_id]
            table = yield slave.callRemote('list_agents')
            resp += [table]
            resp += []
        defer.returnValue("\n".join(resp))

    @manhole.expose()
    def get_slave(self, slave_id):
        '''get_slave(slave_id) -> Give the reference to the nth slave
        agency.'''
        return self._broker.slaves[slave_id]

    # Config manipulation (standalone agencies receive the configuration
    # in the environment).

    def _init_config(self, msg_host=None, msg_port=None,
                     msg_user=None, msg_password=None,
                     db_host=None, db_port=None, db_name=None,
                     public_key=None, private_key=None,
                     authorized_keys=None, manhole_port=None,
                     agency_journal=None, socket_path=None,
                     gateway_port=None):

        def get(value, default=None):
            if value is not None:
                return value
            return default

        msg_conf = dict(host=get(msg_host, DEFAULT_MSG_HOST),
                        port=get(msg_port, DEFAULT_MSG_PORT),
                        user=get(msg_user, DEFAULT_MSG_USER),
                        password=get(msg_password, DEFAULT_MSG_PASSWORD))

        db_conf = dict(host=get(db_host, DEFAULT_DB_HOST),
                       port=get(db_port, DEFAULT_DB_PORT),
                       name=get(db_name, DEFAULT_DB_NAME))

        manhole_conf = dict(public_key=public_key,
                            private_key=private_key,
                            authorized_keys=authorized_keys,
                            port=manhole_port)

        agency_conf = dict(journal=agency_journal,
                           socket_path=socket_path)

        gateway_conf = dict(port=get(gateway_port, DEFAULT_GW_PORT))

        self.config = dict()
        self.config['msg'] = msg_conf
        self.config['db'] = db_conf
        self.config['manhole'] = manhole_conf
        self.config['agency'] = agency_conf
        self.config['gateway'] = gateway_conf

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

    def _start_host_agent_if_necessary(self):
        '''
        This method starts saves the host agent descriptor and runs it.
        To make this happen following conditions needs to be fulfilled:
        - it is a master agency,
        - we are not starting a host agent already,
        - we are not terminating,
        - and last but not least, we dont have a host agent running.
        '''

        def set_flag(value):
            self._starting_host = value

        if self.role != BrokerRole.master:
            # we are not the master agency
            return

        if self._shutting_down:
            # the agency is about to terminate itself
            return

        if self._get_host_agent():
            # we already have host agent
            return

        if self._starting_host:
            # agency if already starting the host agent
            return

        set_flag(True)
        self.info('Starting host agent')
        desc = host.Descriptor(shard=u'lobby')
        conn = self._database.get_connection()

        d = defer.Deferred()
        d.addCallback(defer.drop_param, self.wait_connected)
        d.addCallback(defer.drop_param, conn.save_document, desc)
        d.addCallback(self.start_agent, hostdef=self._hostdef)
        d.addBoth(defer.bridge_param, set_flag, False)
        d.addCallback(defer.drop_param, self._flush_agents_to_spawn)

        time.callLater(0, d.callback, None)

    def _get_host_agent(self):
        medium = self._get_host_medium()
        return medium and medium.get_agent()

    def _get_host_medium(self):
        return first((x for x in self._agents
                      if x.get_descriptor().document_type == 'host_agent'))

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

    def _setup_snapshoter(self):
        self._snapshot_task = time.callLater(300, self._trigger_snapshot)

    def _trigger_snapshot(self):
        self.log("Snapshoting all the agents.")
        self.snapshot_agents()
        self._snapshot_task = None
        self._setup_snapshoter()

    def _force_snapshot_agents(self):
        self.log("Journal has been rotated, forcing snapshot of agents")
        self.snapshot_agents(force=True)

    def _cancel_snapshoter(self):
        if self._snapshot_task is not None and self._snapshot_task.active():
            self._snapshot_task.cancel()
        self._snapshot_task = None

    def _start_slave_gateway(self):
        master_port = int(self.config["gateway"]["port"])
        range = (master_port, master_port + GATEWAY_PORT_COUNT)
        self._gateway = gateway.Gateway(self, range)
        self._gateway.initiate_slave()

    def _start_master_gateway(self):
        master_port = int(self.config["gateway"]["port"])
        range = (master_port, master_port + GATEWAY_PORT_COUNT)
        self._gateway = gateway.Gateway(self, range)
        self._gateway.initiate_master()
