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


__all__ = ("IDatabaseClient", "DatabaseError", "ConflictError",
           "NotFoundError", "NotConnectedError", "IDbConnectionFactory",
           "IDatabaseDriver", "IDbConnectionFactory", "IDocument",
           "IVersionedDocument", "IRevisionStore", "IViewFactory")


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

    def get_attachment_body(doc, attachment):
        '''
        Gets the attachment body.
        @param doc: document to get the attachment
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
        @param doc_id: _id of the document to attach
        @param revision: revision of the document
        @attachment: L{IAttachmentPrivate}
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


class IDocument(Interface):
    '''Interface implemented by objects stored in database.'''

    type_name = Attribute('type identifying the document')
    doc_id = Attribute('id of the document')
    rev = Attribute('revision of the document')
    # name -> IAttachment
    attachments = Attribute('C{dict} of attachments')

    def create_attachment(name, body, content_type='text/plain'):
        '''
        Create an attachment to be saved along with the document.
        Creating an attachments with a already taken name will overwrite it.

        @rtype: L{IAttachment}
        '''

    def delete_attachment(name):
        '''
        Removes the attachments by name. The document still needs to be saved.
        @raises: L{NotFoundError} for unknown name
        '''


class IAttachment(Interface):

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


class IRevisionStore(Interface):
    '''
    Private interface implemented by database connection. It is used by
    RevisionFilter to obtain the information about the documents changed
    by this connection.'''

    known_revisions = Attribute('dict of doc_id -> (last_index, last_hash)')


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

    def map(doc):
        '''
        Function called for every document in the database.
        It has to be a generator yielding tuples (key, value).
        Optional.
        @param doc: document in couchdb
        @type doc: C{dict}. It always has _id and _rev keys. The rest is
                   specific to the application.
        '''

    def reduce(keys, values):
        '''
        Defined optionaly if use_reduce = True.
        Function called with the list of results emited by the map() calls
        for all the documents. It should return a result calculated for
        everything.

        @param keys: Keys generated for the documents being reduced.
        @param values: Values generated for the documents being reduced.
        @return: Resulting value.
        '''

    def filter(document, request):
        '''
        Defined optionaly to create a change/replication filter.
        @param document: The document to be filtered
        @param request: The request object (contains the parameters)
        @return: Flag saying if this document matched the filter.
        '''

    def parse(key, value, reduced):
        '''
        Map the (key, value) pair to the python object of our choice.
        @param reduced: Flag telling if we are parsing the map function
                        result or the reduced data. Usefull for creating
                        views which works both ways.
        @return: Any instance.
        '''
