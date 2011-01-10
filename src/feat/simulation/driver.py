# -*- Mode: Python -*-
# vi:si:et:sw=4:sts=4:ts=4
import StringIO

from twisted.internet import defer
from zope.interface import implements

from feat.common import log, manhole
from feat.agencies import agency
from feat.agencies.emu import messaging, database
from feat.interface.agent import IAgencyAgent
from feat.test import factories
from feat.agents.base import document


class Commands(manhole.Manhole):
    '''
    Implementation of all the commands understood by the protocol.
    This is a mixin mixed to Driver class.
    '''

    @manhole.expose()
    def spawn_agency(self):
        '''
        Spawn new agency, returns the reference. Usage:
        > spawn_agency()
        '''
        ag = agency.Agency(self._messaging, self._database)
        self._agencies.append(ag)
        return ag

    @manhole.expose()
    def descriptor_factory(self, document_type, shard=u'lobby'):
        """
        Creates and returns a descriptor to pass it later
        for starting the agent.
        First parameter is a document_type representing the descirptor.
        Second parameter is optional (default lobby). Usage:
        > descriptor_factory('shard_descriptor', 'some shard')
        """
        desc = factories.build(document_type, shard=unicode(shard))
        return self._database_connection.save_document(desc)

    @manhole.expose()
    def breakpoint(self, name):
        """
        Register the breakpoint of the name. Usage:
        > breakpoint('setup-done')

        The name should be used in a call of Driver.register_breakpoint(name)
        method, which returns the Deferred, which will be fired by this
        command.
        """
        if name not in self._breakpoints:
            self.warning("Reached breakpoint %s but found no "
                         "callback registered")
            return
        cb = self._breakpoints[name]
        cb.callback(None)
        return cb

    @manhole.expose()
    def find_agency(self, agent_id):
        """
        Returns the agency running the agent with agent_id or None.
        """

        def has_agent(agency):
            for agent in agency._agents:
                if agent._descriptor.doc_id == agent_id:
                    return True
            return False

        matching = filter(has_agent, self._agencies)
        if len(matching) > 0:
            self.debug('Find agency returns %dth agency.',
                       self._agencies.index(matching[0]))
            return matching[0]


class Driver(log.Logger, log.FluLogKeeper, Commands):
    implements(IAgencyAgent)

    log_category = 'simulation-driver'

    def __init__(self):
        log.FluLogKeeper.__init__(self)
        log.Logger.__init__(self, self)
        Commands.__init__(self)

        self._messaging = messaging.Messaging()
        self._database = database.Database()

        self._output = Output()
        self._parser = manhole.Parser(self, self._output, self)

        self._agencies = list()
        self._breakpoints = dict()

        self._init_connections()

    def _init_connections(self):

        def store(desc):
            self._descriptor = desc

        self._database_connection = self._database.get_connection(self)
        d = self._database_connection.save_document(
            factories.build('descriptor'))
        d.addCallback(store)

        self._messaging_connection = self._messaging.get_connection(self)

    def register_breakpoint(self, name):
        if name in self._breakpoints:
            raise RuntimeError("Breakpoint with name: %s already registered",
                               name)
        d = defer.Deferred()
        self._breakpoints[name] = d
        return d

    def process(self, script):
        self._parser.dataReceived(script)

    def finished_processing(self):
        '''Called when the protocol runs out of data to process'''

    # IAgencyAgent

    def on_message(self, msg):
        pass

    def get_descriptor(self):
        return self._descriptor

    # Delegation of IDatabase methods for tests

    def reload_document(self, doc):
        assert isinstance(doc, document.Document)
        return self._database_connection.reload_document(doc)

    def get_document(self, doc_id):
        return self._database_connection.get_document(doc_id)


class Output(StringIO.StringIO, object):
    """
    This class is given to parser as an output in unit tests,
    when there is no transport to write to.
    """