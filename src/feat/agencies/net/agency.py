import re

from twisted.internet import reactor, defer

from feat.agents.base.agent import registry_lookup
from feat.agents.base import recipient
from feat.agencies import agency
from feat.agencies.net import ssh, broker
from feat.common import manhole
from feat.interface import agent
from feat.interface.agency import ExecMode
from feat.process import standalone
from feat.common.serialization import json

from feat.agencies.net import messaging
from feat.agencies.net import database


DEFAULT_MSG_HOST = "localhost"
DEFAULT_MSG_PORT = 5672
DEFAULT_MSG_USER = "guest"
DEFAULT_MSG_PASSWORD = "guest"
DEFAULT_DB_HOST = "localhost"
DEFAULT_DB_PORT = 5984
DEFAULT_DB_NAME = "feat"

# Only for command-line options
DEFAULT_MH_PUBKEY = "public.key"
DEFAULT_MH_PRIVKEY = "private.key"
DEFAULT_MH_AUTH = "authorized_keys"
DEFAULT_MH_PORT = 6000


def add_options(parser):
    parser.add_option('-m', '--msghost', dest="msg_host",
                      help="host of messaging server to connect to",
                      metavar="HOST", default=DEFAULT_MSG_HOST)
    parser.add_option('-p', '--msgport', dest="msg_port",
                      help="port of messaging server to connect to",
                      metavar="PORT", default=DEFAULT_MSG_PORT, type="int")
    parser.add_option('-u', '--msguser', dest="msg_user",
                      help="username to loging to messaging server",
                      metavar="USER", default=DEFAULT_MSG_USER)
    parser.add_option('-c', '--msgpass', dest="msg_password",
                      help="password to messaging server",
                      metavar="PASSWORD", default=DEFAULT_MSG_PASSWORD)

    # database related options
    parser.add_option('-H', '--dbhost', dest="db_host",
                      help="host of database server to connect to",
                      metavar="HOST", default=DEFAULT_DB_HOST)
    parser.add_option('-P', '--dbport', dest="db_port",
                      help="port of messaging server to connect to",
                      metavar="PORT", default=DEFAULT_DB_PORT, type="int")
    parser.add_option('-N', '--dbname', dest="db_name",
                      help="host of database server to connect to",
                      metavar="NAME", default=DEFAULT_DB_NAME)

    # manhole specific
    parser.add_option('-k', '--pubkey', dest='manhole_public_key',
                      help="public key used by the manhole",
                      default=DEFAULT_MH_PUBKEY)
    parser.add_option('-K', '--privkey', dest='manhole_private_key',
                      help="private key used by the manhole",
                      default=DEFAULT_MH_PRIVKEY)
    parser.add_option('-A', '--authorized', dest='manhole_authorized_keys',
                      help="file with authorized keys to be used by manhole",
                      default=DEFAULT_MH_AUTH)
    parser.add_option('-M', '--manhole', type="int", dest='manhole_port',
                      help="port for the manhole to listen", metavar="PORT",
                      default=DEFAULT_MH_PORT)


class Agency(agency.Agency):

    @classmethod
    def from_config(cls, env, options=None):
        agency = cls()
        agency._init_config(env, options)
        agency._load_config(env, options)
        agency.initiate()
        return agency

    def __init__(self, msg_host=None, msg_port=None,
                 msg_user=None, msg_password=None,
                 db_host=None, db_port=None, db_name=None,
                 public_key=None, private_key=None,
                 authorized_keys=None, manhole_port=None):

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
                          manhole_port=manhole_port)

        self._ssh = None
        self._broker = None

        # this is default mode for the dependency modules
        self._set_default_mode(ExecMode.production)

    def initiate(self):
        mesg = messaging.Messaging(
            self.config['msg']['host'], int(self.config['msg']['port']),
            self.config['msg']['user'], self.config['msg']['password'])
        db = database.Database(
            self.config['db']['host'], int(self.config['db']['port']),
            self.config['db']['name'])

        super_init = agency.Agency.initiate(self, mesg, db)

        reactor.addSystemEventTrigger('before', 'shutdown',
                                      self.on_killed)

        self._ssh = ssh.ListeningPort(self, **self.config['manhole'])
        self._broker = broker.Broker(self,
                                on_master_cb=self._ssh.start_listening,
                                on_slave_cb=self._ssh.stop_listening,
                                on_disconnected_cb=self._ssh.stop_listening)
        return defer.DeferredList([super_init,
                                   self._broker.initiate_broker()])

    def on_killed(self):
        d = agency.Agency.on_killed(self)
        d.addCallback(lambda _: self._disconnect)
        return d

    @manhole.expose()
    def full_shutdown(self):
        '''full_shutdown() -> Terminate all the slave agencies and shutdowns
        itself.'''
        d = self._broker.shutdown_slaves()
        d.addCallback(lambda _: self.shutdown())
        return d

    @manhole.expose()
    def shutdown(self):
        '''shutdown() -> Shutdown the agency in gentel manner (terminating
        all the agents).'''
        d = agency.Agency.shutdown(self)
        d.addCallback(lambda _: self._disconnect())
        return d

    def _disconnect(self):
        d = defer.succeed(None)
        d.addCallback(lambda _: self._broker.disconnect())
        d.addCallback(lambda _: self._ssh.stop_listening())
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
        cmd, cmd_args, cmd_env = factory.get_cmd_line(*args, **kwargs)
        env = self._store_config(cmd_env)
        env['FEAT_AGENT_ID'] = str(descriptor.doc_id)
        env['FEAT_AGENT_ARGS'] = json.serialize(args)
        env['FEAT_AGENT_KWARGS'] = json.serialize(kwargs)
        recp = recipient.Agent(descriptor.doc_id, descriptor.shard)

        d = self._broker.wait_event(recp.key, 'started')
        d.addCallback(lambda _: recp)

        p = standalone.Process(self, cmd, cmd_args, cmd_env)
        p.restart()

        return d

    # Manhole inspection methods

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
                     authorized_keys=None, manhole_port=None):

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

        self.config = dict()
        self.config['msg'] = msg_conf
        self.config['db'] = db_conf
        self.config['manhole'] = manhole_conf

    def _store_config(self, env):
        '''
        Stores agency config into environment to be read by the
        standalone agency.'''
        for key in self.config:
            for kkey in self.config[key]:
                var_name = "FEAT_%s_%s" % (key.upper(), kkey.upper(), )
                env[var_name] = str(self.config[key][kkey])
        return env

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
                    self.config[c_key][c_kkey] = value

        # Then override with options
        if options:
            for group_key, conf_group in self.config.items():
                for conf_key in conf_group:
                    attr = "%s_%s" % (group_key, conf_key)
                    if hasattr(options, attr):
                        conf_group[conf_key] = getattr(options, attr)
