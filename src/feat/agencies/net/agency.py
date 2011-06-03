import optparse
import re

from twisted.internet import reactor
from zope.interface import implements

from feat.agents.base.agent import registry_lookup
from feat.agents.base import recipient
from feat.agencies import agency, journaler
from feat.agencies.net import ssh, broker
from feat.common import manhole, defer, time
from feat.interface import agent
from feat.interface.agency import ExecMode
from feat.process import standalone
from feat.common.serialization import json
from feat.gateway import gateway

from feat.agencies.net import messaging
from feat.agencies.net import database


DEFAULT_SOCKET_PATH = None # Use broker default
DEFAULT_MSG_HOST = "localhost"
DEFAULT_MSG_PORT = 5672
DEFAULT_MSG_USER = "guest"
DEFAULT_MSG_PASSWORD = "guest"
DEFAULT_DB_HOST = "localhost"
DEFAULT_DB_PORT = 5984
DEFAULT_DB_NAME = "feat"
DEFAULT_JOURFILE = 'journal.sqlite3'
DEFAULT_GW_PORT = 7777

# Only for command-line options
DEFAULT_MH_PUBKEY = "public.key"
DEFAULT_MH_PRIVKEY = "private.key"
DEFAULT_MH_AUTH = "authorized_keys"
DEFAULT_MH_PORT = 6000


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


class Agency(agency.Agency):

    implements(gateway.IResolver)

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

    @property
    def gateway_port(self):
        return self._gateway and self._gateway.port

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

        self._ssh = ssh.ListeningPort(self, **self.config['manhole'])
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

    def on_become_master(self):
        self._ssh.start_listening()
        self._journal_writer = journaler.SqliteWriter(
            self, filename=self.config['agency']['journal'], encoding='zip')
        self._journaler.configure_with(self._journal_writer)
        self._journal_writer.initiate()
        self._start_master_gateway(self.config["gateway"]["port"])

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
        #FIXME: we may stop the gateway here, but then we should handle
        #       asynchronous server shutdown when it's restarted

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
        self._cancel_snapshoter()
        d = agency.Agency.shutdown(self)
        d.addCallback(defer.drop_param, self._disconnect)
        return d

    def _disconnect(self):
        d = defer.succeed(None)
        d.addCallback(defer.drop_param, self._broker.disconnect)
        d.addCallback(defer.drop_param, self._ssh.stop_listening)
        return d

    @manhole.expose()
    def start_agent(self, descriptor, *args, **kwargs):
        """
        Starting an agent is delegated to the broker, who makes sure that
        this method will be eventually run on the master agency.
        """
        return self._broker.start_agent(descriptor, *args, **kwargs)

    def actually_start_agent(self, descriptor, *args, **kwargs):
        """
        This method will be run only on the master agency.
        """
        factory = agent.IAgentFactory(
            registry_lookup(descriptor.document_type))
        if factory.standalone:
            return self.start_standalone_agent(descriptor, factory,
                                               *args, **kwargs)
        else:
            return self.start_agent_locally(descriptor, *args, **kwargs)

    def start_agent_locally(self, descriptor, *args, **kwargs):
        return agency.Agency.start_agent(self, descriptor, *args, **kwargs)

    def start_standalone_agent(self, descriptor, factory, *args, **kwargs):
        cmd, cmd_args, env = factory.get_cmd_line(*args, **kwargs)
        self._store_config(env)
        env['FEAT_AGENT_ID'] = str(descriptor.doc_id)
        env['FEAT_AGENT_ARGS'] = json.serialize(args)
        env['FEAT_AGENT_KWARGS'] = json.serialize(kwargs)
        recp = recipient.Agent(descriptor.doc_id, descriptor.shard)

        d = self._broker.wait_event(recp.key, 'started')
        d.addCallback(lambda _: recp)

        p = standalone.Process(self, cmd, cmd_args, env)
        p.restart()

        return d

    ### gateway.IResolver ###

    def resolve(self, recipient):
        pass

    ### Manhole inspection methods ###

    @manhole.expose()
    def find_agent_locally(self, agent_id):
        '''find_agent_locally(agent_id_or_descriptor) -> Same as find_agent
        but only checks in scope of this agency.'''
        return agency.Agency.find_agent(self, agent_id)

    @manhole.expose()
    def find_agent(self, agent_id):
        '''find_agent(agent_id_or_descriptor) -> Gives medium class of the
        agent if the agency hosts it.'''
        return self._broker.find_agent(agent_id)

    @manhole.expose()
    @defer.inlineCallbacks
    def list_slaves(self):
        '''list_slaves() -> Print information about the slave agencies.'''
        num = len(self._broker.slaves)
        resp = []
        for slave, i in zip(self._broker.slaves, range(num)):
            resp += ["#### Slave %d ####" % i]
            table = yield slave.callRemote('list_agents')
            resp += [table]
            resp += []
        defer.returnValue("\n".join(resp))

    @manhole.expose()
    def get_nth_slave(self, n):
        '''get_nth_slave(n) -> Give the reference to the nth slave agency.'''
        return self._broker.slaves[n]

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

    def _setup_snapshoter(self):
        self._snapshot_task = time.callLater(300, self._trigger_snapshot)

    def _trigger_snapshot(self):
        self.log("Snapshoting all the agents.")
        self.snapshot_agents()
        self._snapshot_task = None
        self._setup_snapshoter()

    def _cancel_snapshoter(self):
        if self._snapshot_task is not None and self._snapshot_task.active():
            self._snapshot_task.cancel()
        self._snapshot_task = None

    def _start_slave_gateway(self):

        def startit(_):
            self.info("Starting slave gateway")
            self._gateway = gateway.Gateway(self, 0)
            return self._gateway.initialise()

        d = self._stop_gateway()
        d.addCallback(startit)
        return d

    def _start_master_gateway(self, port):

        def startit(_):
            self.info("Starting master gateway on port %d", port)
            self._gateway = gateway.Gateway(self, port)
            return self._gateway.initialise()

        d = self._stop_gateway()
        d.addCallback(startit)
        return d

    def _stop_gateway(self):
        if self._gateway is not None:
            self.info("Stopping gateway on port %d", self._gateway.port)
            d = self._gateway.cleanup()
            self._gateway = None
            return d
        return defer.succeed(self)
