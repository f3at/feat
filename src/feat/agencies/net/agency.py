import binascii
import base64

from zope.interface import implements
from twisted.cred import portal
from twisted.conch import (avatar, checkers, recvline,
                           interfaces as conchinterfaces, )
from twisted.conch.ssh import factory, keys, session

from twisted.conch.insults import insults
from twisted.internet import reactor

from feat.agencies import agency
from feat.common import manhole

from . import messaging
from . import database


class Agency(agency.Agency):

    def __init__(self, msg_host='localhost', msg_port=5672, msg_user='guest',
                 msg_password='guest',
                 db_host='localhost', db_port=5984, db_name='feat',
                 public_key=None, private_key=None, authorized_keys=None,
                 manhole_port=None):
        mesg = messaging.Messaging(msg_host, msg_port, msg_user, msg_password)
        db = database.Database(db_host, db_port, db_name)
        agency.Agency.__init__(self, mesg, db)

        if manhole_port:
            public_key_str = file(public_key).read()
            private_key_str = file(private_key).read()

            sshFactory = factory.SSHFactory()
            sshFactory.portal = portal.Portal(SSHRealm(self))
            sshFactory.portal.registerChecker(KeyChecker(authorized_keys))

            sshFactory.publicKeys = {
                'ssh-rsa': keys.Key.fromString(data=public_key_str)}
            sshFactory.privateKeys = {
                'ssh-rsa': keys.Key.fromString(data=private_key_str)}

            reactor.listenTCP(manhole_port, sshFactory)


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
        '''Print defined locals names.'''
        return "\n".join(self._locals.keys())

    @manhole.expose()
    def exit(self):
        '''Close connection.'''
        self.terminal.write("Happy hacking!")
        self.terminal.nextLine()
        self.terminal.loseConnection()


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
