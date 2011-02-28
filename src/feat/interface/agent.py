from zope.interface import Interface, Attribute

__all__ = ["IAgentFactory", "IAgencyAgent", "IAgencyAgent", "IAgent"]


class IAgentFactory(Interface):
    '''Create an agent implementing L{IAgent}. Used by the agency when
    starting an agent.'''

    standalone = Attribute("bool. whether to run in standalone process")

    def __call__(medium, *args, **kwargs):
        pass

    def get_cmd_line(*args, **kwargs):
        '''
        Should be implemeneted for the stand alone agents. Returns the
        command line which need to be run to start the external process, its
        arguments and environment.
        @returns: Tuple of the format: (command, args, env).
        '''


class IAgencyAgent(Interface):
    '''Agency part of an agent. Used as a medium by the agent
    L{IAgent} implementation.'''

    agent = Attribute("L{IAgent}")
    agency = Attribute("L{IAgency}")

    def get_descriptor():
        '''
        Return the copy of the descriptor.
        '''

    def update_descriptor(desc):
        '''
        Save the descriptor into the database. This method should be used
        instead of save_document, because agency side of implementation needs
        to keep track of the changes.

        @param desc: Descriptor to save.
        @type desc: feat.agents.base.descriptor.Descriptor
        @returns: Deferred
        '''

    def register_interest(factory):
        '''Registers an interest in a contract or a request.'''

    def revoke_interest(factory):
        '''Revokes any interest in a contract or a request.'''

    def initiate_protocol(factory, recipients, *args, **kwargs):
        '''
        Initiates a contract or a request.

        @type recipients: L{IRecipients}
        @rtype: L{IInitiator}
        @returns: Instance of protocols initiator
        '''

    def retrying_protocol(self, factory, recipients, max_retries,
                         initial_delay, max_delay, args, kwargs):
        '''
        Initiates the protocol which will get restart if it fails.
        The restart will be delayed with exponential growth.

        Extra params comparing to L{IAgencyAgent.initiate_protocol}:

        @param max_retries: After how many retries to give up. Def. None: never
        @param initial_delay: Delay before the first retry.
        @param max_delay: Miximum delay to wait (above it it will not grow).
        @returns: L{RetryingProtocol}
        '''

    def get_time():
        '''
        Use this to get current time. Should fetch the time from NTP server

        @returns: Number of seconds since epoch
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

    def terminate():
        '''
        Performs all the necessary steps to end the life of the agent in a
        gentle way. The termination process consits of following steps:

        1. Revoke all interests.
        2. Terminate all retrying protocols.
        3. Kill all listeners (with making them expire instantly).
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


class IAgent(Interface):
    '''Agent interface. It uses the L{IAgencyAgent} given at initialization
    time in order to perform its task.'''

    def initiate(*args, **kwargs):
        '''
        Called after the agent is registered to an agency.
        Args and keywords are passed to IAgency.start_agent().
        '''

    def get_descriptor():
        '''Returns a copy of the agent descriptos.'''

    def shutdown():
        """
        Called after agency decides to terminate the agent.
        Agent code should take care to notify all it's his contractors
        that the collaboration is over.
        """
