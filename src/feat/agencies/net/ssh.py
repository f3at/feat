import pprint
import binascii
import base64

from zope.interface import implements
from twisted.cred import portal
from twisted.conch import (avatar, checkers, recvline,
                           interfaces as conchinterfaces, )
from twisted.conch.ssh import factory, keys, session
from twisted.internet.error import CannotListenError
from twisted.internet import reactor
from twisted.conch.insults import insults

from feat.common import log, manhole


class ListeningPort(log.Logger):

    def __init__(self, agency, public_key=None, private_key=None,
                 authorized_keys=None, port=6000):
        log.Logger.__init__(self, agency)

        self.agency = agency
        self._listener = None
        self.sshFactory = None
        self.port = port

        if not (public_key and private_key and authorized_keys):
            self.info('Skipping manhole configuration. You need to specify '
                      'public and private key files and authorized_keys file.')
            return

        try:
            public_key_str = file(public_key).read()
            private_key_str = file(private_key).read()

            self.sshFactory = factory.SSHFactory()
            self.sshFactory.portal = portal.Portal(SSHRealm(self.agency))
            self.sshFactory.portal.registerChecker(KeyChecker(authorized_keys))

            self.sshFactory.publicKeys = {
                'ssh-rsa': keys.Key.fromString(data=public_key_str)}
            self.sshFactory.privateKeys = {
                'ssh-rsa': keys.Key.fromString(data=private_key_str)}
        except IOError as e:
            self.sshFactory = None
            self.error('Failed to setup the manhole. File missing. %r', e)
            return

    def start_listening(self):
        try:
            if self.sshFactory:
                self._listener = reactor.listenTCP(self.port, self.sshFactory)
                self.info('Manhole listening on port: %d.', self.port)
        except CannotListenError as e:
            self.error('Cannot setup manhole. Reason: %r', e)

    def stop_listening(self):
        if self._listener:
            self.info('Closing manhole listener.')
            return self._listener.stopListening()


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
