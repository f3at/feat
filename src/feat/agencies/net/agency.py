import pprint
import re
import binascii
import base64

from zope.interface import implements
from twisted.cred import portal
from twisted.conch import (avatar, checkers, recvline,
                           interfaces as conchinterfaces, )
from twisted.conch.ssh import factory, keys, session

from twisted.conch.insults import insults
from twisted.internet import reactor

from feat.agents.base.agent import registry_lookup
from feat.agencies import agency
from feat.common import manhole
from feat.interface import agent

from . import messaging
from . import database


class Agency(agency.Agency):

    def __init__(self, msg_host='localhost', msg_port=5672, msg_user='guest',
                 msg_password='guest',
                 db_host='localhost', db_port=5984, db_name='feat',
                 public_key=None, private_key=None, authorized_keys=None,
                 manhole_port=None):

        self.config = dict()
        self.config['msg'] = dict(host=msg_host, port=msg_port,
                                  user=msg_user, password = msg_password)
        self.config['db'] = dict(host=db_host, port=db_port, name=db_name)
        self.config['manhole'] = dict(public_key=public_key,
                                      private_key=private_key,
                                      authorized_keys=authorized_keys,
                                      port=manhole_port)

        self._init_networking()

    def _init_networking(self):
        mesg = messaging.Messaging(
            self.config['msg']['host'], self.config['msg']['port'],
            self.config['msg']['user'], self.config['msg']['password'])
        db = database.Database(
            self.config['db']['host'], self.config['db']['port'],
            self.config['db']['name'])
        agency.Agency.__init__(self, mesg, db)

        self._setup_manhole()

    def _setup_manhole(self):
        self._manhole_listener = None

        try:
            public_key_str = file(self.config['manhole']['public_key']).read()
            private_key_str = file(
                self.config['manhole']['private_key']).read()

            sshFactory = factory.SSHFactory()
            sshFactory.portal = portal.Portal(SSHRealm(self))
            sshFactory.portal.registerChecker(KeyChecker(
                self.config['manhole']['authorized_keys']))

            sshFactory.publicKeys = {
                'ssh-rsa': keys.Key.fromString(data=public_key_str)}
            sshFactory.privateKeys = {
                'ssh-rsa': keys.Key.fromString(data=private_key_str)}
        except IOError as e:
            self.error('Failed to setup the manhole. File missing. %r', e)
            return

        if self.config['manhole']['port'] is None:
            self.config['manhole']['port'] = 6000

        while True:
            try:
                self._manhole_listener = reactor.listenTCP(
                    self.config['manhole']['port'], sshFactory)
                self.info('Manhole listening on the port: %d',
                          self.config['manhole']['port'])
                break
            except CannotListenError:
                self.config['manhole']['port'] += 1

    def shutdown(self):
        d = agency.Agency.shutdown(self)
        if self._manhole_listener:
            d.addCallback(lambda _: self._manhole_listener.stopListening())
        return d

    @manhole.expose()
    def start_agent(self, descriptor, *args, **kwargs):
        factory = agent.IAgentFactory(
            registry_lookup(descriptor.document_type))
        if not factory.standalone:
            return agency.Agency.start_agent(self, descriptor, *args, **kwargs)
        else:
            command, args, env = factory.get_cmd_line()
            env = self._store_config(env)
            env['FEAT_AGENT_ID'] = descriptor.doc_id
            p = standalone.Process(self, command, args, env)
            return p.restart()

    def _store_config(self, env):
        '''
        Stores agency config into environment to be read by the
        standalone agency.'''
        for key in self.config:
            for kkey in self.config[key]:
                var_name = "FEAT_%s_%s" % (key.upper(), kkey.upper(), )
                env[var_name] = self.config[key][kkey]
        return env

    def _load_config(self, env):
        '''
        Loads config from environment.
        '''
        self.config = dict()
        matcher = re.compile('\AFEAT_([^_]+)_(.+)\Z')
        for key in env:
            res = matcher.search(key)
            if res:
                c_key = res.group(1).lower()
                c_kkey = res.group(2).lower()
                if c_key in self.config:
                    self.config[c_key][c_kkey] = env[key]
                else:
                    self.config[c_key] = {c_kkey: env[key]}


class KeyChecker(checkers.SSHPublicKeyDatabase):

    def __init__(self, keyfile):
        self.keys = []
        f = open(keyfile)
        for l in f.readlines():
            l2 = l.split()
            if len(l2) < 2:
                continue
            try:
                self.keys.append(base64.decodestring(l2[1]))
            except binascii.Error:
                continue
        f.close()

    def check_key(self, key):
        try:
            next(x for x in self.keys if x == key.blob)
            return 1
        except StopIteration:
            return 0


class SSHProtocol(manhole.Parser, recvline.HistoricRecvLine, manhole.Manhole):

    def __init__(self, ag):
        recvline.HistoricRecvLine.__init__(self)
        self.agency = ag
        manhole.Parser.__init__(self, ag, None, self)

    def connectionMade(self):
        recvline.HistoricRecvLine.connectionMade(self)
        self.output = self.terminal
        self.set_local(self.agency, 'agency')
        self.terminal.write("Welcome to the manhole! Type help() for info.")
        self.terminal.nextLine()
        self.showPrompt()

    def showPrompt(self):
        self.terminal.write("> ")

    def lineReceived(self, line):
        manhole.Parser.dataReceived(self, line+'\n')

    def on_finish(self):
        self.showPrompt()

    @manhole.expose()
    def locals(self):
        '''locals() -> Print defined locals names.'''
        return "\n".join(self._locals.keys())

    @manhole.expose()
    def exit(self):
        '''exit() -> Close connection.'''
        self.terminal.write("Happy hacking!")
        self.terminal.nextLine()
        self.terminal.loseConnection()

    @manhole.expose()
    def get_document(self, doc_id):
        '''get_document(doc_id) -> Download the document given the id.'''
        conn = self.agency._database.get_connection(None)
        return conn.get_document(doc_id)

    @manhole.expose()
    def pprint(self, obj):
        '''pprint(obj) -> Preaty print the object'''
        return pprint.pformat(obj)

    @manhole.expose()
    def list_get(self, llist, index):
        """list_get(list, n) -> Get the n'th element of the list"""
        return llist[index]


class SSHAvatar(avatar.ConchUser):
    implements(conchinterfaces.ISession)

    def __init__(self, username, ag):
        avatar.ConchUser.__init__(self)
        self.username = username
        self.agency = ag
        self.channelLookup.update({'session': session.SSHSession})

    def openShell(self, protocol):
        serverProtocol = insults.ServerProtocol(SSHProtocol, self.agency)
        serverProtocol.makeConnection(protocol)
        protocol.makeConnection(session.wrapProtocol(serverProtocol))

    def windowChanged(self, winSize):
        pass

    def getPty(self, terminal, windowSize, attrs):
        return None

    def execCommand(self, protocol, cmd):
        raise NotImplementedError

    def closed(self):
        pass


class SSHRealm(object):
    implements(portal.IRealm)

    def __init__(self, agency):
        self.agency = agency

    def requestAvatar(self, avatarId, mind, *interfaces):
        if conchinterfaces.IConchUser in interfaces:
            return interfaces[0], SSHAvatar(avatarId, self.agency),\
                   lambda: None
        else:
            raise Exception("No supported interfaces found.")
