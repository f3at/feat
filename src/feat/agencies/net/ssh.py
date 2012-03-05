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
import pprint
import binascii
import base64
import os
import sys

from zope.interface import implements
from twisted.cred import portal
from twisted.conch import (avatar, checkers, recvline,
                           interfaces as conchinterfaces, )
from twisted.conch.ssh import factory, keys, session
from twisted.internet.error import CannotListenError
from twisted.internet import reactor
from twisted.conch.insults import insults

from feat.common import log, manhole, reflect
from feat.agencies import recipient


def commands_factory(agency):

    def wrapper():
        return Commands(agency)

    return wrapper


class Commands(manhole.Manhole, manhole.Parser):

    def __init__(self, agency):
        manhole.Parser.__init__(self, agency, output=None, commands=self)

        self.agency = agency
        self.set_local(self.agency, 'agency')

    def on_finish(self):
        self.output.write("> ")

    ### methods exposed as root level ###

    @manhole.expose()
    def locals(self):
        '''Print defined locals names.'''
        return "\n".join(self._locals.keys())

    @manhole.expose()
    def exit(self):
        '''Close connection.'''
        self.output.write("Happy hacking!")
        self.output.nextLine()
        self.output.loseConnection()

    @manhole.expose()
    def get_document(self, doc_id):
        '''Download the document given the id.'''
        conn = self.agency._database.get_connection()
        return conn.get_document(doc_id)

    @manhole.expose()
    def recp(self, a_id, shard):
        '''get_document(agent_id, shard) -> Construct IRecipient poining to
        the agent'''
        return recipient.Agent(a_id, shard)

    @manhole.expose()
    def pprint(self, obj):
        '''Preaty print the object'''
        return pprint.pformat(obj)

    @manhole.expose()
    def list_get(self, llist, index):
        """Get the n'th element of the list"""
        return llist[index]

    @manhole.expose()
    def shutdown(self):
        """Perfrom full agency shutdown. Cleanup slave agency and
        agents descriptor."""
        return self.agency.full_shutdown(stop_process=True)

    @manhole.expose()
    def import_module(self, module):
        '''Load the given module to memory.'''
        return reflect.named_module(module)

    @manhole.expose()
    def get_agent(self, agent_type, index=0):
        '''Returns the agent instance for the
        given agent_type. Optional index tells which one to give.'''
        return self.get_medium(agent_type, index).get_agent()

    @manhole.expose()
    def get_medium(self, agent_type, index=0):
        '''Returns the medium class for the
        given agent_type. Optional index tells which one to give.'''
        mediums = list(x for x in self.agency._agents
                       if x.get_descriptor().type_name == agent_type)
        try:
            return mediums[index]
        except KeyError:
            raise RuntimeError(
                'Requested medium class of %s with index %d, but found only '
                '%d medium of this type'
                % (agent_type, index, len(mediums))), None, sys.exc_info()[2]

    @manhole.expose()
    def restart_agent(self, agent_id, **kwargs):
        '''tells the host agent running in this agency to restart the agent.'''
        host_medium = self.get_medium('host_agent')
        agent = host_medium.get_agent()
        d = host_medium.get_document(agent_id)
        # This is done like this on purpose, we want to ensure that document
        # exists before passing it to the agent (even though he would handle
        # this himself).
        d.addCallback(
            lambda desc: agent.start_agent(desc.doc_id, **kwargs))
        return d


class ListeningPort(log.Logger):

    def __init__(self, logger, parser_factory, public_key=None,
                 private_key=None, authorized_keys=None, port=None):
        log.Logger.__init__(self, logger)

        self._listener = None
        self.sshFactory = None
        self.port = port or 6000

        if not (public_key and private_key and authorized_keys):
            self.info('Skipping manhole configuration. You need to specify '
                      'public and private key files and authorized_keys file.')
            return

        try:
            public_key_str = file(public_key).read()
        except IOError as e:
            self.sshFactory = None
            self.warning("Failed to setup the manhole. File '%s' missing. %r",
                public_key, e)
            return
        try:
            private_key_str = file(private_key).read()
        except IOError as e:
            self.sshFactory = None
            self.warning("Failed to setup the manhole. File '%s' missing. %r",
                private_key, e)
            return

        try:
            self.sshFactory = factory.SSHFactory()
            self.sshFactory.portal = portal.Portal(SSHRealm(parser_factory))
            self.sshFactory.portal.registerChecker(KeyChecker(authorized_keys))

            self.sshFactory.publicKeys = {
                'ssh-rsa': keys.Key.fromString(data=public_key_str)}
            self.sshFactory.privateKeys = {
                'ssh-rsa': keys.Key.fromString(data=private_key_str)}
        except IOError as e:
            self.sshFactory = None
            self.warning('Failed to setup the manhole. File missing. %r', e)
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
        self._keyfile = keyfile

    def checkKey(self, credentials):
        """
        Retrieve the keys of the user specified by the credentials, and check
        if one matches the blob in the credentials.
        """
        filename = self._keyfile
        if not os.path.exists(filename):
            return 0
        lines = open(filename).xreadlines()
        for l in lines:
            l2 = l.split()
            if len(l2) < 2:
                continue
            try:
                if base64.decodestring(l2[1]) == credentials.blob:
                    return 1
            except binascii.Error:
                continue
        return 0


class SSHProtocol(recvline.HistoricRecvLine):

    def __init__(self, parser_factory):
        recvline.HistoricRecvLine.__init__(self)
        if not callable(parser_factory):
            self._wrong_parser(parser_factory)

        self.parser = parser_factory()
        if not isinstance(self.parser, manhole.Parser):
            self._wrong_parser(self.parser)

    def _wrong_parser(self, arg):
            raise TypeError("Expected first param to be a callable giving the "
                            "f.c.manhole.Parser instance. Got %r instead." %
                            arg)

    def connectionMade(self):
        recvline.HistoricRecvLine.connectionMade(self)
        self.parser.output = self.terminal
        self.terminal.write("Welcome to the manhole! Type help() for info.")
        self.terminal.nextLine()
        self.parser.on_finish()

    def lineReceived(self, line):
        self.parser.dataReceived(line + '\n')


class SSHAvatar(avatar.ConchUser):
    implements(conchinterfaces.ISession)

    def __init__(self, username, parser_factory):
        avatar.ConchUser.__init__(self)
        self.username = username
        self.parser_factory = parser_factory
        self.channelLookup.update({'session': session.SSHSession})

    def openShell(self, protocol):
        serverProtocol = insults.ServerProtocol(SSHProtocol,
                                                self.parser_factory)
        serverProtocol.makeConnection(protocol)
        protocol.makeConnection(session.wrapProtocol(serverProtocol))

    def windowChanged(self, winSize):
        pass

    def getPty(self, terminal, windowSize, attrs):
        return None

    def execCommand(self, protocol, cmd):
        parser = self.parser_factory()
        parser.output = protocol
        parser.on_finish = protocol.loseConnection
        protocol.makeConnection(_DummyTransport())
        parser.dataReceived(cmd + '\n')

    def closed(self):
        pass


class SSHRealm(object):
    implements(portal.IRealm)

    def __init__(self, parser_factory):
        self.parser_factory = parser_factory

    def requestAvatar(self, avatarId, mind, *interfaces):
        if conchinterfaces.IConchUser in interfaces:
            return interfaces[0], SSHAvatar(avatarId, self.parser_factory),\
                   lambda: None
        else:
            raise Exception("No supported interfaces found.")


class _DummyTransport(object):

    def loseConnection(self):
        pass
