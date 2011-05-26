from zope.interface import Interface, Attribute
from feat.common import enum

__all__ = ["IAgentFactory", "IAgencyAgent", "IAgencyAgent", "IAgent",
           "AgencyAgentState", "Access", "Address", "Storage",
           "CategoryError"]


class CategoryError(RuntimeError):
    """
    Raised when categories don't match with the
    categories defined in the HostAgent.
    """


class Access(enum.Enum):
    '''
    If the machine can be accessed from outside
    '''

    none, public, private = range(3)


class Address(enum.Enum):
    '''
    If the machine network address can change or is fixed
    '''

    none, fixed, dynamic = range(3)


class Storage(enum.Enum):
    '''
    If the machine storage is reliable upon restart is shared amongst other
    machines in the same site.
    '''

    none, static, shared, volatile = range(4)


class IAgentFactory(Interface):
    '''Create an agent implementing L{IAgent}. Used by the agency when
    starting an agent.'''

    standalone = Attribute("bool. whether to run in standalone process")

    categories = Attribute("Dict. Access, Address and Storage")

    restart_strategy = Attribute(
        "L{feat.agents.common.monitor.RestartStrategy}")

    def __call__(medium, *args, **kwargs):
        pass

    def get_cmd_line(*args, **kwargs):
        '''
        Should be implemeneted for the stand alone agents. Returns the
        command line which need to be run to start the external process, its
        arguments and environment.
        @returns: Tuple of the format: (command, args, env).
        '''


class AgencyAgentState(enum.Enum):
    '''
    not_initiated - Agent is not initialized
    initiating    - Agent is currently initializing
    initiated     - Initialize done
    starting_up   - Agent starting up
    ready         - Agent is ready
    error         - Agent has throw an exception
    '''
    (not_initiated, initiating, initiated,
     starting_up, started, ready, error) = range(7)


class IAgencyAgent(Interface):
    '''Agency part of an agent. Used as a medium by the agent
    L{IAgent} implementation.'''

    agent = Attribute("L{IAgent}")
    agency = Attribute("L{IAgency}")

    def observe(callable, *args, **kwargs):
        """
        Observes the asynchronous method result.
        The callable may return Fiber or Deferred.
        Use it if you want to know keep the
        information about the result of the fiber without keeping the
        reference to the original object. This is usefull when dealing with
        transient object like Tasks, Managers, etc. Examples:

        observer = state.medium.observe(task.notify_finish)
        ....
        f = observer.notify_finish()
        (do sth with f)

        Synchronous methods:
        if not observer.active():
          res = oserver.get_result()

        @type fiber: L{feat.interface.fiber.IFiber}
        @rtype: L{feat.interface.fiber.IObserver}
        """

    def get_descriptor():
        '''
        Return the copy of the descriptor.
        '''

    def get_configuration():
        '''
        Return a copy of the agents metadocument with configuration.
        '''

    def update_descriptor(callable, *args, **kwargs):
        '''
        Schedule a descriptor update.
        The specified callable will be called when all pending descriptor
        updates are done with the last descriptor value and the specified
        arguments.
         - The callable can modify the descriptor and return a result.
         - The callable must be synchronous.
         - The callable cannot return a deferred or a fiber.
         - When the callable returns, the updated descriptor is saved.
         - The returned deferred is fired with the callable result.

        This method should be used instead of save_document because:
         - agency queue descriptor updates to be sure only one happen at a time
           preventing conflicts.
         - agency side of implementation needs to keep track of the changes.

        @param callable: Synchronous function that update a descriptor.
        @type callable: function
        @returns: Deferred
        '''

    def join_shard(shard_id):
        '''Joins shard with specified identifier.'''

    def leave_shard(shard_id):
        '''Leave the shard with specified identifier.'''

    def register_interest(factory):
        '''Registers an interest in a contract or a request.'''

    def revoke_interest(factory):
        '''Revokes any interest in a contract or a request.'''

    def initiate_protocol(factory, *args, **kwargs):
        '''
        Initiates a contract or a request.
        Arguments varies in function of the specified factory.

        @rtype: L{IInitiator}
        @returns: Instance of protocols initiator
        '''

    def retrying_protocol(self, factory, recipients=None,
                          max_retries=None, initial_delay=1,
                          max_delay=None, args=None, kwargs=None):
        '''
        Initiates the protocol which will get restart if it fails.
        The restart will be delayed with exponential growth.

        Extra params comparing to L{IAgencyAgent.initiate_protocol}:

        @param max_retries: After how many retries to give up. Def. None: never
        @param initial_delay: Delay before the first retry.
        @param max_delay: Miximum delay to wait (above it it will not grow).
        @returns: L{RetryingProtocol}
        '''

    def periodic_protocol(self, factory, period, *args, **kwargs):
        '''
        Will start specified protocol periodically.
        @returns: L{PeriodicProtocol}
        '''

    def save_document(document):
        '''
        Save the document into the database. Document might have been loaded
        from the database before, or has just been constructed.

        If the doc_id
        property of the document is not set, it will be loaded from the
        database.

        @param document: Document to be saved.
        @type document: Subclass of L{feat.agents.document.Document}
        @returns: Deferred called with the updated Document (id and revision
                  set)
        '''

    def get_document(document_id):
        '''
        Download the document from the database and instantiate it.
        The document should have the 'document_type' basing on which we decide
        which subclass of L{feat.agents.document.Document} to instantiate.

        @param document_id: The id of the document in the database.
        @returns: The Deffered called with the instance representing downloaded
                  document.
        '''

    def reload_document(document):
        '''
        Fetch the latest revision of the document and update it.

        @param document: Document to update.
        @type document: Subclass of L{feat.agents.document.Document}.
        @returns: Deferred called with the updated instance.
        '''

    def delete_document(document):
        '''
        Marks the document in the database as deleted. The document
        returns in the deferred can still be used in the application.
        For example one can call save_document on it to bring it back.

        @param document: Document to be deleted.
        @type document: Subclass of L{feat.agents.document.Document}.
        @returns: Deferred called with the updated document (latest revision).
        '''

    def query_view(factory, **options):
        '''
        Queries the database view.

        It only supports small part of CouchDB features. In production
        implementation the options are just passed to the query. This means
        that basicly everything is supported. In emu database implementation
        the only supported option is:
        - reduce C{boolean}: optionaly lets fetch the result of the map from
          the map-reduce view (skips the reduce part).
        In case you want to use more features of CouchDB you should implement
        them feat.agencies.emu.database.Database, and test their intergration
        in feat.test.integration.test_idatabase_client.

        @param factory: View factory to query.
        @type factory: L{feat.interface.view.IViewFactory}
        @param options: Dictionary of parameters to pass to the query.
        @return: C{list} of the results.
        '''

    def terminate():
        '''
        Performs all the necessary steps to end the life of the agent in a
        gentle way. The termination process consits of following steps:

        1. Revoke all interests.
        2. Terminate all retrying protocols.
        3. Kill all protocols (with making them expire instantly).
        4. Run the IAgent.shutdown() and wait for it to finish.
        5. Run the IAgent.unregister() - responsibility of this method to
           perform agent-side shutdown part common to all agents.
        6. Remove agents descriptor from the database.
        7. Delete the agents queue.

        @returns: Deferred.
        '''

    def get_mode(component):
        '''
        Get the mode to run given component.
        '''

    def wait_for_state(state):
        '''
        Wait for for specific state
        '''

    def get_machine_state():
        '''
        Returns the current state
        '''

    def call_next(method, *args, **kwargs):
        '''
        Calls the method outside the current execution chain.
        @returns: The call id which can be used to cancel the call.
        '''

    def call_later(time_left, method, *args, **kwargs):
        '''
        Calls the method in future.
        @returns: The call id which can be used to cancel the call.
        '''

    def cancel_delayed_call(call_id):
        '''
        Cancels the delayed call.
        '''


class IAgent(Interface):
    '''Agent interface. It uses the L{IAgencyAgent} given at initialization
    time in order to perform its task.'''

    def initiate(*args, **kwargs):
        '''
        Called after the agent is registered to an agency.
        Args and keywords are passed to IAgency.start_agent().
        '''

    def startup():
        '''Called when initiate has finished'''

    def get_descriptor():
        '''Returns a copy of the agent descriptos.'''

    def get_agent_id():
        '''Returns a global unique identifier for the agent.
        Do not change when the agent is restarted.'''

    def get_instance_id():
        '''Returns the agent instance identifier.
        Changes when the agent is restarted.
        It's unique only for the agent.'''

    def get_full_id():
        '''Return a global unique identifier for this agent instance.
        It's a combination of agent_id and instance_id:
          full_id = agent_id + "/" + instance_id
        '''

    def shutdown():
        """
        Called after agency decides to terminate the agent.
        Agent code should take care to notify all it's his contractors
        that the collaboration is over.
        """

    def on_killed():
        '''
        Called as part of the SIGTERM handler. This type of shutdown assumes
        that the monitoring agent will restart us somewhere.
        '''
