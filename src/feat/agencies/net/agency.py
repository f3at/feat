import optparse
import re

from twisted.internet import reactor, error
from zope.interface import implements
from twisted.spread import pb

from feat.agents.base.agent import registry_lookup
from feat.agents.base import recipient
from feat.agencies import agency, journaler
from feat.agencies.net import ssh, broker
from feat.common import manhole, defer, time
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
DEFAULT_DB_HOST = "localhost"
DEFAULT_DB_PORT = 5984
DEFAULT_DB_NAME = "feat"
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

    @manhole.expose()
    def get_gateway_port(self):
        return self._gateway and self._gateway.port

    gateway_port = property(get_gateway_port)

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
        self._ssh = ssh.ListeningPort(self,
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
        self._cancel_snapshoter()
        d = agency.Agency.shutdown(self)
        d.addCallback(defer.drop_param, self._disconnect)
        return d

    def _disconnect(self):
        d = defer.succeed(None)
        d.addCallback(defer.drop_param, self._ssh.stop_listening)
        d.addCallback(defer.drop_param, self._gateway.cleanup)
        d.addCallback(defer.drop_param, self._broker.disconnect)
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
        factory = IAgentFactory(
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

    ### Manhole inspection methods ###

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
        slaves = list(self._broker.iter_slaves())
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

    @defer.inlineCallbacks
    def _find_agent(self, agent_id):
        '''
        Specific to master agency, called by the broker.
        Will return AgencyAgent if agent is hosted by master agency,
        PB.Reference if it runs in stanadlone or None if it was not found.
        '''
        local = self.find_agent_locally(agent_id)
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
