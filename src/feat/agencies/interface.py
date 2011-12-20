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
# -*- Mode: Python -*-
# vi:si:et:sw=4:sts=4:ts=4

from zope.interface import Interface, Attribute

from feat.common import enum

__all__ = ("AgencyRoles",
           "IAgencyProtocolInternal", "IAgencyListenerInternal",
           "IAgencyAgentInternal",
           "IAgencyInitiatorFactory", "IAgencyInterestFactory",
           "IAgencyInterestInternalFactory", "ILongRunningProtocol",
           "IAgencyInterestInternal", "IAgencyInterestedFactory",
           "IDatabaseClient",
           "DatabaseError", "ConflictError", "NotFoundError",
           "NotConnectedError",
           "IFirstMessage", "IDialogMessage", "IDbConnectionFactory",
           "IDatabaseDriver", "IJournaler", "IRecord", "IJournalerConnection",
           "IJournalWriter")


class AgencyRoles(enum.Enum):
    unknown, master, slave, standalone = range(4)


class DatabaseError(RuntimeError):
    '''
    Base class for database specific exceptions
    '''


class ConflictError(DatabaseError):
    '''
    Raised when we encounter revision mismatch.
    '''


class NotFoundError(DatabaseError):
    '''
    Raised when we request document which is not there
    or has been deleted.
    FIXME: Should be moved to feat.interface.
    '''


class NotConnectedError(Exception):
    '''
    Raised when we get connection refused trying to perform a request to
    database.
    FIXME: Should be moved to feat.interface.
    '''


class IAgencyProtocolInternal(Interface):
    '''Represents a protocol which can be registered in AgencyAgent.'''

    guid = Attribute("Protocol globally unique identifier.")

    def cleanup(self):
        '''Called by the agency when terminating,
        it should cancel the protocol. Returns a deferred.'''

    def is_idle(self):
        '''Returns if the protocol is in idle state.'''

    def get_agent_side():
        '''
        @returns: the instance of agent-side protocol
        '''

    def notify_finish():
        '''
        @returns: Deferred which will be run after the protocol has finished.
        '''


class IAgencyListenerInternal(Interface):

    def on_message(message):
        '''hook called when message arrives'''


class IAgencyAgentInternal(Interface):
    '''Internal interface of an agency agent.'''

    def get_agent():
        pass

    def create_binding(prot_id, shard):
        '''
        @return: feat.agencies.messaging.interface.IChannelBinding
        '''

    def release_binding(binding):
        '''
        @type binding: feat.agencies.messaging.interface.IChannelBinding
        '''

    def register_protocol(protocol):
        '''@type protocol: IAgencyProtocolInternal'''

    def unregister_protocol(protocol):
        '''@type protocol: IAgencyProtocolInternal'''

    def send_msg(recipients, msg, handover=False):
        pass

    def journal_protocol_created(factory, medium, *args, **kwargs):
        pass


class IAgencyInterestFactory(Interface):
    '''Factory constructing L{IAgencyInterest} instances.'''

    def __call__(factory):
        '''Creates a new agency interest
        for the specified agent-side factory.'''


class IAgencyInterestInternalFactory(Interface):
    '''Factory constructing L{IAgencyInterestInternal} instances.'''

    def __call__(agency_agent):
        '''Creates a new internal agency interest
        for the specified agent-side factory.'''


class IAgencyInterestInternal(Interface):

    factory = Attribute("Agent-side protocol factory.")

    def bind(shard):
        '''Create a binding for the specified shard.'''

    def revoke():
        '''Revoke the current bindings to the current shard.'''

    def schedule_message(message):
        '''Schedules the handling of a the specified message.'''

    def clear_queue():
        '''Clears the message queue.'''

    def wait_finished():
        '''Returns a Deferred that will be fired when there is no more
        active or queued messages.'''

    def is_idle():
        '''Returns True if there is no active or queued messages.'''


class IAgencyInitiatorFactory(Interface):
    '''Factory constructing L{IAgencyInitiator} instance.'''

    def __call__(agency_agent, recipients, *args, **kwargs):
        '''Creates a new agency initiator
        for the specified agent-side factory.'''


class IAgencyInterestedFactory(Interface):
    '''Factory constructing L{IAgencyInterested} instance.'''

    def __call__(agency_agent, message):
        '''Creates a new agency interested
        for the specified agent-side factory.'''


class ILongRunningProtocol(Interface):
    '''Long running protocol that could be cancelled.'''

    def is_idle():
        '''Returns if the protocol is idle.'''

    def cancel():
        '''Cancel the protocol.'''

    def notify_finish():
        '''Returns a deferred fired when the protocol finishes.'''


class IFirstMessage(Interface):
    '''
    This interface needs to be implemeneted by the message object which is
    the first one in the dialog. Implemeneted by: Announcement, Request.
    '''

    traversal_id = Attribute('Unique identifier. It is preserved during '
                             'nesting between shard, to detect duplications.')


class IDbConnectionFactory(Interface):
    '''
    Responsible for creating connection to database server.
    Should be implemented by database drivers passed to the agency.
    '''

    def get_connection():
        '''
        Instantiate the connection for the agent.

        @returns: L{IDatabaseClient}
        '''


class IDialogMessage(Interface):
    '''
    This interface needs to be implemeneted by the message
    objects which take part on a dialog.
    '''

    reply_to = Attribute("The recipient to send the response to.")
    sender_id = Attribute("The sender unique identifier.")
    receiver_id = Attribute("The receiver unique identifier.")


class IDatabaseClient(Interface):

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

    def changes_listener(doc_ids, callback):
        '''
        Register a callback called when the document is changed.
        If different=True (defualt) only changes triggered by this session
        are ignored.
        @param document: Document ids to look to
        @param callback: Callable to call
        @param different: Flag telling whether to ignore changes triggered
                          by this session.
        '''

    def query_view(factory, **options):
        '''
        @param factory: View factory to query.
        @type factory: L{feat.interface.view.IViewFactory}
        @param options: Dictionary of parameters to pass to the query.
        @return: C{list} of results.
        '''

    def disconnect():
        '''
        Disconnect from database server.
        '''

    def create_database():
        '''
        Request creating the database.
        '''


class IDatabaseDriver(Interface):
    '''
    Interface implemeneted by the database driver.
    '''

    def create_db():
        '''
        Request creating the database.
        '''

    def save_doc(doc, doc_id=None):
        '''
        Create new or update existing document.
        @param doc: string with json document
        @param doc_id: id of the document
        @return: Deferred fired with the HTTP response body (keys: id, rev)
        '''

    def open_doc(doc_id):
        '''
        Fetch document from database.
        @param doc_id: id of the document to fetch
        @return: Deferred fired with json parsed document.
        '''

    def delete_doc(doc_id, revision):
        '''
        Mark document as delete.
        @param doc_id: id of document to delete
        @param revision: revision of the document
        @return: Deferred fired with dict(id, rev) or errbacked with
                 ConflictError
        '''

    def listen_changes(doc_ids, callback):
        '''
        Register callback called when one of the documents get changed.
        @param doc_ids: list of document ids which we are interested in
        @param callback: callback to call, it will get doc_id and revision
        @return: Deferred trigger with unique listener identifier
        @rtype: Deferred
        '''

    def cancel_listener(listener_id):
        '''
        Unregister callback called on document changes.
        @param listener_id: Id returned buy listen_changes() method
        @rtype: Deferred
        @return: Deferred which will fire when the listener is cancelled.
        '''

    def query_view(factory, **options):
        '''
        Query the view. See L{IDatabaseClient.query_view}.
        '''


class IJournaler(Interface):
    """
    Interface implemented by object responsible for storing/querying journal
    entries. It also constructs the connections used by the agencies.
    """

    def get_connection(agency):
        """
        Creates the connection for the agency to push it's entries.
        @param agency: The agency for which to create the journal entries.
        @type agency: L{feat.interfaces.serialization.IExternalizer}
        @return: Connection instance
        @rtype: L{IJournalerConnection}
        """

    def prepare_record():
        '''
        Preconstruct a IRecord instance which is used as data container.
        @rtype: L{IRecord}
        '''

    def is_idle():
        """
        Returns bool saying if there are pending entries to get flushed.
        """


class IRecord(Interface):
    '''
    Interface implemented by the data container used to comunicate beetween
    IJournalKeeper and IJournaler.
    '''

    def commit(**data):
        '''
        Commits the entry. The dictionary should contain the following keys:
        agent_id           - id of the agent
        instance_id        - id of the instance
        journal_id         - serialized id of the IRecorder
        function_id        - id of the journaled function called
        args               - serialized arguments of the call
        kwargs             - serialized keywords of the call
        fiber_id           - id of the fiber
        fiber_depth        - depth in the fiber
        result             - serialized result of the call
        side_effects       - serialized list of side effects produced
                             by the call
        '''


class IJournalerConnection(Interface):
    """
    Interface implemented by connection from agency to journaler.
    It acts as a factory for the IJournalEntries, and tracks the instances
    it produces.
    """

    def new_entry(agent_id, journal_id, function_id, *args, **kwargs):
        """
        Create a new IAgencyJournalEntry for the given parameters.
        @rtype: IAgencyJournalEntry
        """

    def snapshot(agent_id, instance_id, snapshot):
        """
        Create special IAgencyJournalEntry representing agent snapshot.
        """


class IJournalWriter(Interface):
    '''
    Layer responsible for persisitng the jounal entries.
    '''

    def insert_entries(entries):
        '''
        Write the entries to the transport.
        '''

    def is_idle():
        """
        Returns bool saying if there are pending entries to get flushed.
        """

    def configure_with(journaler):
        """
        Binds journal writer to a journaler. This is used for calling
        callbacks.
        """


class IJournalReader(Interface):

    def get_histories():
        '''
        Returns the Deferred triggered with list history objects stored in
        journal.
        @rtype: Deferred([L{feat.agencies.journal.History}])
        '''

    def get_entries(history):
        '''
        Fetches the journal entries for given history. History object contains
        the information about the agent_id and instance_id.

        The trigger value of returned Deferred is the list of journal entries.
        Single entry is a dictionary with the keys:
        - agent_id,
        - instance_id,
        - journal_id,
        - function_id,
        - fiber_id,
        - fiber_depth,
        - args,
        - kwargs,
        - side_effects,
        - result,
        - timestamp,
        - entry_type = "journal"

        @param history: History object interesting us.
        @type history: L{feat.agencies.journal.History}
        @rtype: Deferred(list)
        '''

    def get_bare_journal_entries(limit):
        '''
        Returns journal entries "from the top of the table". This is used
        by migration procedure of entries.
        @rtype: Same as get_entries() method
        '''

    def delete_top_journal_entries(num):
        '''
        Deletes journal entries from the database. It will remove entries
        "from the top of the table" meaning with lowest timestamp.
        '''

    def delete_top_log_entries(num):
        '''
        Deletes log entries from the database. It will remove entries
        "from the top of the table" meaning with lowest timestamp.
        '''

    def get_log_entries(start_date, end_data, filters, limit):
        '''
        Fetches the log entries for the given period of time and filters.
        All parameters are optional, by default this query will return
        all the entries.

        The return format is a list dictionaries with keys:
        - message,
        - level,
        - category,
        - log_name,
        - file_path,
        - line_num,
        - timestamp
        - entry_type = "log"

        @type start_data, end_data: C{int} epoch time.
        @param filters: List of dictionaries containg following keys:
                  - level (log level)
                  - category (log category)
                  - name (log name)
                  - hostname (hostname)
                  If the key is not present its simply not taken into account
                  for the filter. If multiple filters are specified they are
                  combined with the OR operator in the query.
        @param limit: maxium number of log entries to fetch
        @rtype: Deferred
        '''

    def get_log_hostnames(start_date, end_date):
        '''
        Fetches the hostnames for which we have log entries in the journal.
        Parameters are optional and passed in epoch time format. (int)

        @param start_date: epoch time to start search
        @param end_date: epoch time to end search
        @callback: list of unicode
        '''

    def get_log_categories(start_date, end_date, hostname):
        '''
        Fetch the log categories for the entries of the given period of time.
        Parameters are optional and passed in epoch time format. (int)

        @param start_date: epoch time to start search
        @param end_date: epoch time to end search
        @param hostname: hostname for which we are asking
        @callback: list of unicode.
        '''

    def get_log_names(category, hostname, start_date, end_date):
        '''
        Fetch the list of log_name for the given category in the period of
        time.
        @param start_date: epoch time to start search
        @param end_date: epoch time to end search
        @rtype: Deferred
        @callback: list of strings
        '''

    def get_log_time_boundaries():
        '''
        @rtype: Deferred
        @callback: a tuple of log entry timestaps (first, last) or None
        '''


class IRevisionStore(Interface):
    '''
    Private interface implemented by database connection. It is used by
    RevisionFilter to obtain the information about the documents changed
    by this connection.'''

    known_revisions = Attribute('dict of doc_id -> (last_index, last_hash)')
