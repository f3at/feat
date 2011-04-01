# -*- Mode: Python -*-
# vi:si:et:sw=4:sts=4:ts=4
import StringIO
import uuid

from zope.interface import implements

from feat.common import log, manhole, defer, reflect
from feat.agencies import agency, dependency
from feat.agencies.emu import messaging, database
from feat.interface.agency import ExecMode
from feat.test import factories
from feat.agents.base import document, descriptor, dbtools
from feat.agents.shard import shard_agent


class Commands(manhole.Manhole):
    '''
    Implementation of all the commands understood by the protocol.
    This is a mixin mixed to Driver class.
    '''

    @manhole.expose()
    def spawn_agency(self, *components):
        '''
        Spawn new agency, returns the reference. Usage:
        > spawn_agency()
        Also takes a list of components to switch into production mode.
        By default all the components work in test mode.
        Components are the canonical names of interfaces classes used by
        dependencies (example: flt.agents.hapi.interface.IServerFactory).
        '''
        ag = agency.Agency()
        self._agencies.append(ag)
        for canonical_name in components:
            comp = reflect.named_object(canonical_name)
            ag.set_mode(comp, ExecMode.production)
        d = ag.initiate(self._messaging, self._database)
        d.addCallback(defer.override_result, ag)
        return d

    @manhole.expose()
    def uuid(self):
        '''
        Generates random string.
        '''
        return str(uuid.uuid1())

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

    @manhole.expose()
    def find_agent(self, agent_id):
        """
        Return the medium class of the agent with agent_id if the one is
        running in simulation.
        """
        if isinstance(agent_id, descriptor.Descriptor):
            agent_id = agent_id.doc_id
        agency = self.find_agency(agent_id)
        return agency and agency.find_agent(agent_id)

    @manhole.expose()
    def count_shard_kings(self):
        res = 0
        for medium in self.iter_agents():
            agent = medium.get_agent()
            if not isinstance(agent, shard_agent.ShardAgent):
                continue
            if agent.is_king():
                res += 1
        return res

    @manhole.expose()
    def validate_shards(self):
        error = False
        for medium in self.iter_agents():
            agent = medium.get_agent()
            if not isinstance(agent, shard_agent.ShardAgent):
                continue
            _, alloc = agent.list_resource()
            allocated = alloc['neighbours']
            part = len(agent.query_partners('neighbours'))
            if allocated != part:
                self.error("Shard Agent of shard %r has %d allocated "
                           "resource and %d partners",
                           medium._descriptor.shard, allocated, part)
                error = True
            if part < 3 and agent.is_peasant():
                self.error(
                    "Shard Agent of shard %r has only %d partners and "
                    "is not a king", medium._descriptor.shard, part)
                error = True
        if not error:
            self.info('All ok!')


class Driver(log.Logger, log.FluLogKeeper, Commands):

    log_category = 'simulation-driver'

    def __init__(self):
        log.FluLogKeeper.__init__(self)
        log.Logger.__init__(self, self)
        Commands.__init__(self)

        self._messaging = messaging.Messaging()
        self._database = database.Database()

        self._output = Output()
        self._parser = manhole.Parser(self, self._output, self,
                                      self.finished_processing)

        self._agencies = list()
        self._breakpoints = dict()

        self._init_connections()

    def _init_connections(self):
        self._database_connection = self._database.get_connection(self)
        dbtools.push_initial_data(self._database_connection)

    def iter_agents(self):
        for agency in self._agencies:
            for agent in agency._agents:
                yield agent

    def register_breakpoint(self, name):
        if name in self._breakpoints:
            raise RuntimeError("Breakpoint with name: %s already registered",
                               name)
        d = defer.Deferred()
        self._breakpoints[name] = d
        return d

    def get_additional_parser(self, cb=None):
        return manhole.Parser(self, self._output, self, cb)

    def process(self, script):
        self._parser.dataReceived(script)

    def finished_processing(self):
        '''Called when the protocol runs out of data to process'''

    # Delegation of IDatabase methods for tests

    def reload_document(self, doc):
        assert isinstance(doc, document.Document)
        return self._database_connection.reload_document(doc)

    def get_document(self, doc_id):
        return self._database_connection.get_document(doc_id)

    def save_document(self, doc):
        return self._database_connection.save_document(doc)


class Output(StringIO.StringIO, object):
    """
    This class is given to parser as an output in unit tests,
    when there is no transport to write to.
    """
