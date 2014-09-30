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


__all__ = ("VERSION_ATOM", "IDatabaseClient", "DatabaseError", "ConflictError",
           "NotFoundError", "NotConnectedError", "ResignFromModifying",
           "IDbConnectionFactory",
           "IDatabaseDriver", "IDbConnectionFactory", "IDocument",
           "IVersionedDocument", "IRevisionStore", "IViewFactory",
           "IPlanBuilder", "IQueryFactory", "IQueryField", "IMigration",
           "ConflictResolutionStrategy")


VERSION_ATOM = u".version"
CURRENT_VERSION_ATOM = u'.skip_version_adaptation'


class DatabaseError(Exception):
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
    '''


class NotConnectedError(Exception):
    '''
    Raised when we get connection refused trying to perform a request to
    database.
    '''


class NotMigratable(DatabaseError):
    '''
    Thrown when we cannot figure out how to upgrade the document loaded
    from the database.

    @ivar args: triple of (class_name, version_from, version_to)
    @type args: triple of (str, int, int)
    '''


class ResignFromModifying(Exception):
    """
    Raised by a callable passed to IDatabaseClient.update_document
    to indicate that it doesn't want to change the document after all.
    This might happen for example is call is supposed to set some value
    inside the document, but this change has been applied by a concurrent
    connection.
    """


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


class DataNotAvailable(DatabaseError):
    '''
    Raised by get_body() call of attachment when the local data is not
    available.
    '''


class IDatabaseClient(Interface):

    database = Attribute("IDatabaseDriver this connection is connected to.")

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

        @param document_id: The id of the document in the database.
        @returns: The Deffered called with the instance representing downloaded
                  document.
        '''

    def copy_document(document_or_id, destination_id, rev):
        '''
        Copy a document to a new location.

        @param document_or_id: IDocument, dict or C{str} document id
        @param destination_id: or to copy to
        @param rev: optional revision, needed to overwrite the existing doc
        @errback: NotFoundError
        @errback: ConflictError
        '''

    def update_document(document_or_id, method, *args, **kwargs):
        '''
        Update the document concurrently. This works by trying to update
        document in a loop and handling the conflicts. The callable is called
        for the document passed and the result is saved to database.
        If a conflict should occur, the latest version of the document is
        fetched and the callable is called again.

        @param method: Method to be called to update the document.
                       It should take the document instance as the first
                       parameter. Additionally it may take extra positional
                       and keyword arguments. To update the document the
                       callable should return the update document instance.
                       Returning None leads to deleting the document.
                       To resign from modifying raise ResignFromModifying.
        @callback: Updated document
        '''

    def get_attachment_body(attachment):
        '''
        Gets the attachment body.
        @param attachment: L{IAttachment}
        @rtype: Deferred
        @callback: C{unicode} attachment body
        @errback: L{NotFoundError}
        '''

    def get_revision(document_id):
        '''
        Get the document revision without parsing it.
        @param document_id: The id of the document in the database.
        @rtype: Deferred
        @callback: revision
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

        @param doc_ids:  Document ids to look to
        @param callback: Callable to call
        '''

    def query_view(factory, **options):
        '''
        @param factory: View factory to query.
        @type  factory: L{feat.interface.view.IViewFactory}
        @param options: Dictionary of parameters to pass to the query.

        @rtype: C{list} of results.
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

    def delete_db():
        '''
        Request deleting the database.
        '''

    def replicate(source, target, **options):
        '''
        Request replication of the database.
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

    def copy_doc(doc_id, destination_id, revision):
        '''
        Copies the document to a new location. Revision is optional, pass it
        to overwrite the existing document.
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

    def save_attachment(doc_id, revision, attachment):
        '''
        Saves the attachment to the database.

        @param doc_id:     _id of the document to attach
        @param revision:   revision of the document
        @type  attachment: L{IAttachmentPrivate}
        '''

    def get_attachment(doc_id, name):
        '''
        Gets the attachment body.
        @param doc_id: id of the document
        @param name: name of the attachment
        @rtype: Deferred
        @callback: C{unicode} attachment body
        @errback: L{NotFoundError}
        '''

    def get_update_seq():
        '''
        @rtype: Deferred
        @callback: C{int} databse sequence number
        '''

    def get_changes(filter, limit, since):
        '''
        Returns information about the changes done to the database since
        the specified revision.
        @param filter: IViewFactory or None
        @param limit: optionally limit the data
        @param since: update_seq of database to start changes
        @rtype: Deferred
        @callback: C{dict} of the following form
           {"results":[
               {"seq":1,"id":"test",
                "changes":[{"rev":"1-aaa8e2a031bca334f50b48b6682fb486"}]}],
            "last_seq":1}
        '''

    def bulk_get(doc_ids):
        '''
        Like get_document() but returns multiple documents in a single request.
        @param doc_ids: C{list} of doc_ids to fetch
        @rtype: Deferred
        @callback: list of documents
        '''

    def get_query_cache(self, create=True):
        '''Called by methods inside feat.database.query module to obtain
        the query cache.
        @param create: C{bool} if True cache will be initialized if it doesnt
                       exist yet, returns None otherwise
        '''


class IDocument(Interface):
    '''Interface implemented by objects stored in database.'''

    type_name = Attribute('type identifying the document')
    doc_id = Attribute('id of the document')
    rev = Attribute('revision of the document')
    # name -> IAttachment
    attachments = Attribute('C{dict} of attachments')
    conflict_resolution_strategy = Attribute('L{ConflictResolutionStrategy}')

    def create_attachment(name, body, content_type='text/plain'):
        '''
        Create an attachment to be saved along with the document.
        Creating an attachments with a already taken name will overwrite it.

        @rtype: L{IAttachment}
        '''

    def delete_attachment(name):
        '''
        Removes the attachments by name. The document still needs to be saved.

        @raise L{NotFoundError}: for unknown name
        '''


class IAttachment(Interface):

    doc_id = Attribute('C{str} id of the document its attachted to')
    name = Attribute('C{str} name of attachment')


class IAttachmentPrivate(IAttachment):

    saved = Attribute('C{bool} flag saying if this attachment is already '
                      'save to the database')
    content_type = Attribute('C{str} content-type')
    length = Attribute('C{int} length')
    has_body = Attribute('C{bool} flag saying that the content is no '
                         'available in memory and need to be downloaded')

    def get_body():
        '''
        @rtype: C{unicode}
        @raises: L{DataNotAvailable}
        '''

    def to_public():
        '''
        Convert attachment to public interface which can be refrenced
        from inside of document body.
        @rtype: L{IAttachment}
        '''

    def set_body(body):
        '''
        Stores in memory the body of the attachment.
        '''

    def set_saved():
        '''
        Marks as saved
        '''


class IDocumentPrivate(Interface):
    '''
    Api used on document objects by database client.
    '''

    def get_attachments(self):
        '''
        @rtype: C{dict} of name -> IAttachmentPrivate
        '''


class IVersionedDocument(IDocument):

    version = Attribute('C{int} current version')
    has_migrated = Attribute('C{bool} flag saying if the document has '
                             'been migrated after loading it from database')

    def get_asynchronous_actions():
        '''
        @returns: [(IMigration, context)]
        '''


class IRevisionStore(Interface):
    '''
    Private interface implemented by database connection. It is used by
    RevisionFilter to obtain the information about the documents changed
    by this connection.'''

    known_revisions = Attribute('dict of doc_id -> (last_index, last_hash)')
    analyzes_locked = Attribute('C{bool} flag saying that at the moment the'
                                ' notifications should not be processed')

    def wait_unlocked(callback):
        '''
        @type callback: {callable}

        Register a callback to be called when the Revision Analityc can
        process his notifications.
        '''


class IViewFactory(Interface):
    '''
    Interface implemented by a view class. It exposes methods getting data
    about necessary for building design document and to parse the result
    of the query.
    '''

    name = Attribute('C{unicode}. Unique name of the view')
    use_reduce = Attribute('C{bool}. Should the reduce function be used')
    design_doc_id = Attribute('C{unicode}. The id of the design_doc to put'
                              ' this view in.')
    language = Attribute('C{unicode}. Language the of the view methods.')
    disable_reduce_limit = Attribute('C{bool}. Should CouchDB be configured '
                                     'to not use the reduce_limit')

    def perform_map(doc):
        '''
        Function called for every document in the database.
        It has to be a generator yielding tuples (key, value).
        Optional.
        @param doc: document in couchdb
        @type doc: C{dict}. It always has _id and _rev keys. The rest is
                   specific to the application.
        '''

    def perform_reduce(keys, values):
        '''
        Defined optionaly if use_reduce = True.
        Function called with the list of results emited by the map() calls
        for all the documents. It should return a result calculated for
        everything.

        @param keys: Keys generated for the documents being reduced.
        @param values: Values generated for the documents being reduced.
        @return: Resulting value.
        '''

    def perform_filter(document, request):
        '''
        Defined optionaly to create a change/replication filter.
        @param document: The document to be filtered
        @param request: The request object (contains the parameters)
        @return: Flag saying if this document matched the filter.
        '''

    def parse_view_result(rows, reduced, include_docs):
        '''
        @param rows: list of tuples of length 2, 3, or 4 depending on how
                     the view was queryied.
        @param reduced: Flag telling if we are parsing the map function
                        result or the reduced data. If True, the rows is a list
                        of tuples of (key, value), if False see below
        @param include_docs: Flag saying if the view have been queried with
                             include_docs. If True the tuples are of the form
                             (key, value, id, doc), if False: (key, value, id);
                             applied reduced=False
        @return: list of any instances.
        '''

    def get_code(name):
        '''
        Gets the source code of the query method.
        '''


class IQueryFactory(Interface):

    fields = Attribute("C{list} of str. Names of fields defined by this view")
    name = Attribute("C{name}")


class IQueryField(Interface):

    field = Attribute("C{str}")
    keeps_value = Attribute("C{bool} flag saying if the IQueryIndex returned "
                            "by this subquery can be used to extract the "
                            "values of each row")

    def fetch(connection, condition, if_modified_since=None):
        '''
        Fetch the value range for a condition.
        @param connection: L{IDatabaseConnection}
        @param condition: L{feat.database.query.Condition}
        @param if_modified_since: optional epoch time; if specified the cache
                                  will not perform the query if it has a
                                  matching entry not older than specified
        @callback: L{IQueryIndex}
        '''


class IQueryIndex(Interface):

    includes_values = Attribute("C{bool} flag saying if the index "
                                "can be used to extract the "
                                "values of each row")
    entries = Attribute("C{list} of sorted ids returned by the index")

    def get_value(id):
        '''
        Extract a value for a ID, only works if includes_values==True
        @returns: value or None
        '''


class IPlanBuilder(Interface):

    def get_basic_queries():
        '''
        Returns a list of tuples: (field, operator, value)
        '''


class IMigration(Interface):
    '''
    Interface implemented by objects which can be registred with
    application.register_migration().
    '''

    type_name = Attribute('Type for which this migration runs')
    source_ver = Attribute('C{int} version of the snapshot source')
    target_ver = Attribute('C{int} version of the snapshot target')

    def synchronous_hook(snapshot):
        '''
        Synchronous method converting the snapshot between versions.
        It should either return a dict with a snapshot or a tuple of the
        form:
        return snapshot, context

        In the second case, the context object will be passed to the
        asynchronous part of the migration which is run after the
        migration has been processed.

        @rtype: C{dict} with adapted snapshot or C{tuple} of snapshot, context.
        '''

    def asynchronous_hook(connection, document, context):
        '''
        @param document: unserializer document instance
        @param context: context returned by adapt_snapshot()
        '''


class ConflictResolutionStrategy(enum.Enum):
    '''
    How should conflict resoultion mechanism handle this document type.

     - db_winner - winner elected by database is fine
     - alert     - use this for document types, where conflict should never
                   happen detecting the conflict will result in raise an alert
                   with the necessary information
     - merge     - documents of this type, should only be updated with
                   update_document() calls. This will create a special document
                   with all the information necessary to later recreate the
                   change if conflict happens.
    '''

    db_winner, alert, merge = range(3)
