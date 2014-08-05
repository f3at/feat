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

from zope.interface import Interface, Attribute

from feat.common import enum, error

__all__ = ["ResponseTypes", "ActionCategories",
           "ValueTypes", "ErrorTypes",
           "ModelError", "TransientError", "BadReference",
           "NotSupported", "Unauthorized", "NotAvailable",
           "ActionFailed", "ActionConflict",
           "ParameterError", "MissingParameters",
           "UnknownParameters", "InvalidParameters",
           "IMetadata", "IMetadataItem",
           "IOfficer", "IContext",
           "IReference", "IRelativeReference",
           "ILocalReference", "IAbsoluteReference",
           "IModel", "IAttribute", "IResponse",
           "IModelItem", "IModelAction", "IActionParam",
           "IValueInfo", "IValueCollection", "IValueList", "IValueRange",
           "IEncodingInfo", "IValueOptions", "IValueOption",
           "IActionPayload", "IErrorPayload", "IQueryModel"]


class ResponseTypes(enum.Enum):
    """
    Types of response model that an action could return:
     - created: The action resulted in a new model being created successfully.
     - updates: The action resulted in the model being updated successfully.
     - deleted: The action resulted in the model being deleted successfully.
     - done: The action has been done successfully.
     """
    created, updated, deleted, accepted, done, error = range(6)


class ActionCategories(enum.Enum):
    """
    Types of action models can provide:
     - retrieve: a state less action that retrieve data.
     - create: an action that will create a new model.
     - update: an action that will update an existing model.
     - delete: an action that will delete a model.
     - command: other types of actions.
     """
    retrieve, create, update, delete, command = range(5)


class ValueTypes(enum.Enum):
    """
    Types of values action value, parameters and result could be:
     - struct: any complex structure.
     - model: a response model.
     - reference: a reference to a model.
     - integer: an integer value.
     - number: an integer or a float
     - boolean: True or False
     - string: a unicode string
     - collection: a collection of other value.
     - binary: a binary blob.
    """
    (struct, model, reference,
     integer, number,
     boolean, string,
     collection, binary) = range(9)


class ErrorTypes(enum.Enum):
    """
    Types of parameter error:
     - generic: any error uncovered by the other types.
     - http: http protocol specific error.
     - parameter_error: action parameter error not covered by the other types
     - missing_parameters: missing action parameters.
     - unknown_parameters: unknown action parameters.
     - invalid_parameters: invalid action parameters.
    """
    (generic,
     http,
     parameter_error,
     missing_parameters,
     unknown_parameters,
     invalid_parameters) = range(6)


class ModelError(error.NonCritical):
    """Base exception for model related errors."""

    log_line_template = "%(class_name)s: %(msg)s"


class TransientError(ModelError):
    """Raised when retrieving an entry or performing and action
    was not possible for unexpected reasons, but could be retried later.
    Raised by models backend using unreliable protocol to retrieve data
    and perform actions.
    """


class BadReference(ModelError):
    """Raised when a reference could not be applied
    to the specified context."""


class NotSupported(ModelError):
    """Raised when an operation is not supported by the model backend,
    such like counting dynamic model items or fetching referenced models."""


class Unauthorized(ModelError):
    """Raised when a model operation is not authorized.
    Setting up authentication and authorization is backend depend."""


class NotAvailable(ModelError):
    """Raised when performing an action, fetching or browsing a child
    is not possible because the expected model are gone."""


class ActionFailed(ModelError):
    """Raise when an action failed to be performed.
    It may contains a model with extra information.
    """

    def __init__(self, *args, **kwargs):
        self.model = kwargs.pop('model', None)
        ModelError.__init__(self, *args, **kwargs)


class ActionConflict(ActionFailed):
    """Raised when an action could not be performed because
    it conflict with the current state of the model."""


class ParameterError(ModelError):
    """Raised when an action cannot be performed because
    a required parameter is missing, an unknown parameter
    has been specified or the value failed validation.
    @ivar parameters: parameters that raised the error.
    @type parameters: (str, )
    @ivar error_type: type of parameter error
    @type error_type: ParameterErrorTypes
    """

    def __init__(self, *args, **kwargs):
        self.parameters = tuple(kwargs.pop("params", ()))
        self.error_type = kwargs.pop("error_type", ErrorTypes.parameter_error)
        ModelError.__init__(self, *args, **kwargs)


class MissingParameters(ParameterError):
    """Raised when some required parameters are missing
    to perform an action."""

    def __init__(self, *args, **kwargs):
        kwargs["error_type"] = ErrorTypes.missing_parameters
        ParameterError.__init__(self, *args, **kwargs)


class UnknownParameters(ParameterError):
    """Raised when some required unknown parameters have been specified."""

    def __init__(self, *args, **kwargs):
        kwargs["error_type"] = ErrorTypes.unknown_parameters
        ParameterError.__init__(self, *args, **kwargs)


class InvalidParameters(ParameterError):
    """Raised when some parameters failed validation.
    @ivar reasons: reasons of the validation failure indexed
                   by parameter name.
    @type reasons: {str: str}
    """

    def __init__(self, *args, **kwargs):
        self.reasons = dict(kwargs.pop("params", {}))
        kwargs["params"] = self.reasons.keys()
        kwargs["error_type"] = ErrorTypes.invalid_parameters
        ParameterError.__init__(self, *args, **kwargs)


class IMetadata(Interface):
    """Provides metadata. Some instance can be adapted
    to IMetadata to access extra information."""

    def get_meta(name):
        """
        @param name: name of the metadata to retrieve.
        @type name: unicode
        @return: a metadata item for specified name or None.
        @rtype: IMetadataItem or None
        """

    def iter_meta_names():
        """
        @return: an iterator over metadata names.
        @rtype: iterator over unicode
        """

    def iter_meta(*names):
        """
        @param names: names of the metadata items to iterate over
                      or None to iterate over all items.
        @type names: unicode or None
        @return: an iterator over metadata items.
        @rtype: iterator over IMetadataItem
        """


class IValueInfo(Interface):
    """
    Value descriptor providing information about action's value, parameters
    and result. It provide value validation and conversion.
    May provide IMetadata, IValueList, IValueRange and IValueOptions.
    """

    label = Attribute("Short label. @type: unicode or None")
    desc = Attribute("Long description. @type: unicode or None")
    value_type = Attribute("Value type. @type: ValueTypes")
    use_default = Attribute("If default value should be used. @type: bool")
    default = Attribute("Default value. @type: object")

    def __eq__(other):
        """IValueInfo implements equality operators."""

    def __ne__(other):
        """IValueInfo implements equality operators."""


class IEncodingInfo(Interface):
    mime_type = Attribute("Mime-type of the value if meaningful. "
                          "@type: str or None")
    encoding = Attribute("Encoding information if meaningful. "
                          "@type: str or None")


class IValueCollection(IValueInfo):
    """Define a collection of values."""

    allowed_types = Attribute("Allowed sub types. @type: list of IValueInfo")
    is_ordered = Attribute("If the list order is important. @type: bool")
    min_size = Attribute("Minimum size of the collection. @type: int")
    max_size = Attribute("Maximum size of the collection. @type: int")


class IValueRange(IValueInfo):
    """
    Adds range constraints to a value descriptor.
    Only meaningful for integer value based descriptors.
    The validate method will validate the specified value is inside
    the set of values defined by minimum, maximum and increment.
    """

    minimum = Attribute("Minimum value. @type: int")
    maximum = Attribute("Maximum value. @type: int")
    increment = Attribute("Value increment. @type: int")


class IValueList(Interface):
    """
    Implemented by structured values. Gives list of subvalues.
    """

    fields = Attribute("List of IValueInfo")


class IValueOptions(Interface):
    """
    Adds constraints and information to a value descriptor
    about the set of possible values.
    """

    is_restricted = Attribute("If only the values from the set of options "
                              "are valid. @type: bool")

    def count_options():
        """
        @return: the number of possible options.
        @rtype: int
        """

    def iter_options():
        """
        @return: an iterator over the possible options.
        @rtype: iterator over IValueOption
        """

    def has_option(value):
        """
        @param value: a possible value.
        @type value: object
        @return: if the specified value is available.
        @rtype: bool
        """

    def get_option(value):
        """
        @param value: a possible value.
        @type value: object
        @return: the option for specified value or None
        @rtype: IValueOption or None
        """


class IValueOption(Interface):
    """Descriptor of a possible value with extra information."""

    label = Attribute("Option short label. @type: unicode")
    value = Attribute("Option value. @type: object")

    def __eq__(other):
        """IValueOption implement equality operator."""

    def __ne__(other):
        """IValueOption implement equality operator."""

    def __hash__():
        """IValueOption is hashable."""


class IMetadataItem(Interface):
    """A metadata atom, containing a name, a format and a list of values."""

    name = Attribute("Name of the metadata atom. @type: unicode")
    value = Attribute("Value of metadata atom. @type unicode")
    scheme = Attribute("Metadata format. @type unicode or None")


class IOfficer(Interface):
    """
    Represent the authority in mater of what could be done and what not.
    """

    peer_info = Attribute("Peer information as a security.IPeerInfo")

    def identify_item_name(model, item_name):
        """
        Returns the string representation of the model item
        with specified name. Used for formating error messages.
        @param model: model of the item to be converted.
        @type model: IModel
        @param item_name: item name to identify.
        @type item_name: unicode or str
        @return: a string representation of the specified item name.
        @rtype: unicode
        """

    def identify_item(model, item):
        """
        Returns the string representation of the model item
        with specified name. Used for formating error messages.
        @param model: model of the item to be converted.
        @type model: IModel
        @param item: model item to identify.
        @type item: IModelItem
        @return: a string representation of the specified item.
        @rtype: unicode
        """

    def identify_action_name(model, action_name):
        """
        Returns the string representation of the model action
        with specified name. Used for formating error messages.
        @param model: model of the item to be converted.
        @type model: IModel
        @param action_name: action name to identify.
        @type action_name: unicode or str
        @return: a string representation of the specified action name.
        @rtype: unicode
        """

    def identify_action(model, action):
        """
        Returns the string representation of the model action
        with specified name. Used for formating error messages.
        @param model: model of the item to be converted.
        @type model: IModel
        @param action: model action to identify.
        @type action: IModelAction
        @return: a string representation of the specified action.
        @rtype: unicode
        """

    def is_item_allowed(model, item_name):
        """
        @param model: model of the item to check for permission.
        @type model: IModel
        @param item_name: item name to check for permission.
        @type item_name: unicode or str
        @return: if the current peer is allowed to retrieve
                 the model item with specified name.
        @rtype: bool
        """

    def is_fetch_allowed(model, item):
        """
        @param model: parent of the model that would be fetched.
        @type model: IModel
        @param item: model item the sub-model would be fetched from.
        @type item: IModelItem
        @return: If fetching a model from specified item is allowed.
        """

    def is_browse_allowed(model, item):
        """
        @param model: parent of the model that would be browsed.
        @type model: IModel
        @param item: model item the sub-model would be browsed from.
        @type item: IModelItem
        @return: If browsing a model from specified item is allowed.
        """

    def is_action_allowed(model, action_name):
        """
        @param model: model of the item to check for permission.
        @type model: IModel
        @param action_name: action name to check for permision.
        @type action_name: str or unicode
        @return: if the current peer is allowed to retrieve
                 the model action with specified name.
        @rtype: bool
        """

    def is_perform_allowed(model, action):
        """
        @param model: model of the action to check for permission.
        @type model: IModel
        @param action: action to check for permission.
        @type action: IModelAction
        @return: if the current peer is allowed to perform
                 the specified action.
        @rtype: bool
        """

    def get_fetch_officer(model, item):
        """
        @param model: parent of the model that would be fetched.
        @type model: IModel
        @param item: model item the sub-model would be fetched from.
        @type item: IModelItem
        @return: the officer responsible for the model that would
                 be fetched from specified model item.
        """

    def get_browse_officer(model, item):
        """
        @param model: parent of the model that would be browsed.
        @type model: IModel
        @param item: model item the sub-model would be browsed from.
        @type item: IModelItem
        @return: the officer responsible for the model that would
                 be browsed from specified model item.
        """


class  IContext(Interface):
    """
    Represent a context use in resolving a reference.
    Attributes models and names MUST be matched,
    meaning that the third name MUST be the name the third model
    has been given by its parent model. The name of the root
    model is an identifier
    Because of this match the first element of the location
    is the root model name and should be an empty string.
    """

    models = Attribute("Current chain of model. @type: list of IModel")
    names = Attribute("Current location build from constructing "
                      "the chain of models and starting by an empty "
                      "string. @type: list of unicode")
    remaining = Attribute("Remaining names to get to the targeted model. "
                          "@type: list of unicode")

    def make_action_address(action):
        """Make and address for an action relative to the current context.
        @param action: the action to generate the address from.
        @type action: IModelAction
        @return: unicode or str
        """

    def make_model_address(location):
        """Make and address from a tuple resolved but a reference.
        @param location: an absolute location built
                         from the reference and the context.
        @type location: tuple of unicode
        @return: unicode or str
        """

    def descend(model):
        """Generate new context appending the (name, model) to the path
        @param model: a sub model of the context.
        @type model: IModel
        @return: the new context based on specified model.
        @rtype: IContext
        """


class IReference(Interface):
    """
    A reference to another model, relative or absolute, local or remote.
    May be able to fetch the referenced model.
    Usually provide one of IRelativeReference,
    ILocalReference or IAbsoluteReference.
    May provide IMetadata.
    """

    def resolve(context):
        """
        Applies the reference to the current context
        and returns a global reference.
        The result will depend on the reference type.
        @return: the address build by the context form the result
                 of resolving the reference.
        @rtype: object()
        @raise BadReference: if the reference cannot be applied
                             to the specified context.
        """


class IRelativeReference(IReference):
    """
    A relative reference to another model starting from the first parent
    model with specified identity or the direct parent model if not specified.
    The location is a tuple of unicode string that uniquely identify
    a chain of model items to fetch from the base model to get to
    the referenced model.
    Applying a relative reference will:
     - keeps the root
     - lookups the models identity for the specified base or take the last one
     - appends the referenced location to the base model location
     - appends the difference between last model location and applied location
    """

    base = Attribute("Model identity the reference is relative from "
                     "or None for the current model. @type: unicode or None")
    location = Attribute("Unique location identifying the model "
                         "relative to the parent model. "
                         "@type: tuple of unicode")


class ILocalReference(IReference):
    """
    An absolute reference to another model starting from the same root.
    The location is a tuple of unicode string that uniquely identify
    a chain of model items to fetch from the root model to get to
    the referenced model.
    Applying a relative reference will:
     - keeps the root
     - use the reference location
    """

    location = Attribute("Unique location identifying the model "
                         "relative to the local root model. "
                         "@type: tuple of unicode")


class IAbsoluteReference(IReference):
    """
    An absolute reference to another model starting from specified root model.
    The root is a globally unique identifier of the root model,
    usually a constructed from protocol, host name and port.
    The location is a tuple of unicode string that uniquely identify
    a chain of model items to fetch from the specified root model
    to get to the referenced model.
    Applying a relative reference will return the reference root and location.
    """

    root = Attribute("Globally unique identifier of the root model "
                     "the location start from. @type: unicode")
    location = Attribute("Unique location identifying the model "
                         "relative to the parent model. "
                         "@type: tuple of unicode or None")


class IModel(Interface):
    """
    Data model to retrieve and modify a local or remote entity.
    It provides ways of retrieving actions and children models.
    If iteration of children or actions is not possible iter_actions()
    and iter_items() will raise error NotSupported.
    Could provide IMetadata to provide extra information.
    May provide IMetadata.
    """

    identity = Attribute("Model unique identifier. @type: unicode")
    name = Attribute("Model name. @type: unicode")
    label = Attribute("Short label. @type: unicode or None")
    desc = Attribute("Long description. @type: unicode or None")
    reference = Attribute("Reference to the real model or None. "
                          "@type: IReference or None")

    def initiate(aspect=None, view=None, parent=None, officer=None):
        """
        Initiates a model with specified aspect, view and parent.
        @param aspect: the model aspect.
        @type aspect: IAspect
        @param view: if the mode is a view, contains view value.
        @type view: object()
        @param parent: the parent model if known.
        @type parent: IModel or None
        @param officer: the officer controlling this model.
        @type parent: IOfficer or None
        @return: a deferred fired with the model itself.
        @rtype: defer.Deferred
        @callback: IModel
        """

    def provides_item(name):
        """
        @param name: the name of an item.
        @type name: unicode
        @return: a deferred fired with True if the model provides an item
                 with specified name, False otherwise.
        @rtype: defer.Deferred
        @callback: bool
        @errback TransientError: for unexpected reasons, it wasn't possible
                                 to determine if item is provided by the model
                                 but the operation could be retried later.
        @errback Unauthorized: if the the caller is not authorized
                               to perform the operation.
        @errback NotAvailable: if the model source is not available.
        """

    def count_items():
        """
        @return: a deferred fired with the number of model's items.
        @rtype: defer.Deferred
        @callback: int
        @errback TransientError: if items couldn't be counted for unexpected
                                 reasons, but it could be retried later.
        @errback Unauthorized: if the the caller is not authorized
                               to count the model's items.
        @errback NotAvailable: if the model source is not available.
        @errback NotSupported: if the model do not support counting items.
        """

    def fetch_item(name):
        """
        @param name: the name of the item to fetch.
        @type name: unicode
        @return: a deferred fired with the model's item
                 with specified name or None.
        @rtype: defer.Deferred
        @callback: IModelItem or None
        @errback TransientError: if item couldn't be fetched for unexpected
                                 reasons, but it could be retried later.
        @errback Unauthorized: if the the caller is not authorized
                               to retrieve the model's item.
        @errback NotAvailable: if the model source is not available.
        """

    def fetch_items():
        """
        @return: a deferred fired with the list of model's items.
        @rtype: defer.Deferred
        @callback: list of IModelItem
        @errback TransientError: if item iterator couldn't be fetched
                                 for unexpected reasons, but the operation
                                 could be retried later.
        @errback Unauthorized: if the the caller is not authorized
                               to retrieve the item iterator.
        @errback NotAvailable: if the model source is not available.
        @errback NotSupported: if the model do not support
                               iterating over items.
        """

    def provides_action(name):
        """
        @param name: the name of an action.
        @type name: unicode
        @return: a deferred fired with True if the model provides an action
                 with specified name, False otherwise.
        @rtype: defer.Deferred
        @callback: bool
        @errback TransientError: for unexpected reasons, it wasn't possible
                                 to determine if action is provided by
                                 the model but the operation could be
                                 retried later.
        @errback Unauthorized: if the the caller is not authorized
                               to perform the operation.
        @errback NotAvailable: if the model source is not available.
        """

    def count_actions():
        """
        @return: a deferred fired with the number of model actions.
        @rtype: defer.Deferred()
        @callback: int
        @errback TransientError: if action count couldn't be fetched
                                 for unexpected reasons, but it
                                 could be retried later.
        @errback Unauthorized: if the the caller is not authorized
                               to count model's actions.
        @errback NotAvailable: if the model source is not available.
        @errback NotSupported: if the model do not support
                               counting model's actions.
        """

    def fetch_actions():
        """
        @return: a deferred fired with the list of model's actions.
        @rtype: defer.Deferred
        @callback: list of IModelAction
        @errback TransientError: if action iterator couldn't be fetched
                                 for unexpected reasons, but it
                                 could be retried later.
        @errback Unauthorized: if the the caller is not authorized
                               to retrieve the action iterator.
        @errback NotAvailable: if the model source is not available.
        @errback NotSupported: if the model do not support
                               iterating over actions.
        """

    def fetch_action(name):
        """
        @param name: the name of the action to fetch.
        @type name: unicode
        @return: a deferred fired with the model's action
                 with specified name or None if not found.
        @rtype: defer.Deferred
        @callback: IModelAction or None
        @errback TransientError: if the action couldn't be fetched
                                 for unexpected reasons, but the operation
                                 could be retried later.
        @errback Unauthorized: if the the caller is not authorized
                               to retrieve the model's action.
        @errback NotAvailable: if the model source is not available.
        """

    def perform_action(name, **kwargs):
        '''
        Fetch action and perform it passing arguments and keywords.
        @param name: name of the action to be performed.
        @type name: str or unicode
        @param kwargs: action parameters.
        @type kwargs: dict
        @return: a deferred fired with the action result.
        @rtype: defer.Deferred
        @callback: return value of the action
        @errback AttributeError: if the action does not exist
        @errback TransientError: if the action couldn't be fetched
                                 for unexpected reasons, but the operation
                                 could be retried later.
        @errback Unauthorized: if the the caller is not authorized
                               to retrieve the model's action.
        @errback NotAvailable: if the model source is not available.
        '''


class IQueryModel(IModel):

    def query_items(limit=10, offset=0, **kwargs):
        """
        @return: a deferred fired with a subset of the model's items
                 filtered following the specified parameters.
        @param limit: C{int} how many items to fetch
        @param offset: C{int} offset of the query

        @rtype: defer.Deferred
        @callback: IModel with the items of result of the query
        @errback TransientError: if items couldn't be fetched for unexpected
                                 reasons, but it could be retried later.
        @errback Unauthorized: if the the caller is not authorized
                               to perform the query.
        @errback NotAvailable: if the model source is not available.
        """


class IAttribute(IModel, IValueInfo):
    """
    Helper interface to make it simpler to use attribute models.
    It provide shortcuts method to the set, get and delete actions,
    using the corresponding model actions and provide value
    metadata extracted from actions.
    """

    value_info = Attribute("Attribute value information. @type: IValueInfo")
    is_readable = Attribute("If the attribute can be read. @type: bool")
    is_writable = Attribute("If the attribute can be written. @type: bool")
    is_deletable = Attribute("If the attribute can be deleted. @type: bool")

    def fetch_value():
        """
        @return: a deferred fired with the attribute value.
        @rtype: defer.Deferred
        @callback: any
        @errback TransientError: if couldn't be fetched but could be retried.
        @errback Unauthorized: if the the caller is not authorized
                               to retrieve the the attribute value.
        @errback NotAvailable: if the model source is not available.
        @errback NotSupported: if the attribute do not support reading.
        """

    def update_value(value):
        """
        Push a value to update the model attribute.
        @param value: a value to push in one of the allowed types.
        @type value: object
        @return: a deferred fired with the new value of the attribute.
        @rtype: defer.Deferred
        @callback: object
        @errback TransientError: if the value couldn't be pushed but
                                 the operation could be retried later.
        @errback Unauthorized: if the the caller is not authorized
                               to update the the attribute value.
        @errback NotAvailable: if the model source is not available.
        @errback NotSupported: if the attribute do not support writing.
        """

    def delete_value():
        """
        Deletes the model's attribute. Further calls will raise NotAvailable.
        @return: a deferred fired with the attribute value when the model
                 attribute got deleted.
        @rtype: defer.Deferred
        @callback: object
        @errback TransientError: if the attribute couldn't be deleted
                                 but the operation could be retried later.
        @errback Unauthorized: if the the caller is not authorized
                               to delete the the attribute.
        @errback NotAvailable: if the model source is not available.
        @errback NotSupported: if the attribute do not support deleting.
        """


class IResponse(IModel):
        """
        A model returned as a the result of performing an action.
        It contains extra information about the outcome of the action.
        """

        response_type = Attribute("Type of response. @type: ResponseType")


class IModelItem(Interface):
    """
    Model item descriptor, provide item information and
    the ability to retrieve a model.
    Models can be fetched or browsed, the difference is a hint
    on the purpose of the retrieved model. If the model
    is to be used by itself fetch() should be used, if the
    model is to be used as an intermediate model to retrieve
    a child model browse() should be used.
    The model is free to return different values in function
    of the purpose of the model and maybe retrieve more or less
    information from the data source, but the returned values
    always support IModel or IReference.
    May provide IMetadata.
    """

    name = Attribute("Item name, unique for all model's items. "
                     "@type: unicode")
    label = Attribute("Item short label. @type: unicode or None")
    desc = Attribute("Item long description. @type: unicode or None")
    reference = Attribute("Reference to the model or None "
                          "if the model is detached. "
                          "@type: IReference or None")

    def browse():
        """
        Fetches the model item to be used to browse to a child model.
        @returns: a deferred fired with the item IModel.
        @rtype: defer.Deferred
        @callback: IModel or IReference
        @errback TransientError: if the model couldn't be fetched for
                                 unexpected reasons but the operation
                                 could be retried later.
        @errback Unauthorized: if the the caller is not authorized
                               to browse to the this model.
        @errback NotAvailable: if the model source or item is not available.
        """

    def fetch():
        """
        Fetches the model item to be used by itself.
        @returns: a deferred fired with the item IModel.
        @rtype: defer.Deferred
        @callback: IModel or IReference
        @errback TransientError: if the model couldn't be fetched for
                                 unexpected reasons but the operation
                                 could be retried later.
        @errback Unauthorized: if the the caller is not authorized
                               to fetch this model.
        @errback NotAvailable: if the model source or item is not available.
        """


class IModelAction(Interface):

    name = Attribute("Action name unique for all model's actions. "
                     "@type: unicode")
    reference = Attribute("Action reference or None if the model "
                          "is detached. @type: IReference or None")
    label = Attribute("Action short label. @type: unicode or None")
    desc = Attribute("Action long description. @type: unicode or None")
    category = Attribute("Action category. @type: ActionCategories")
    is_idempotent = Attribute("If performing the action multiple times gives "
                              "the same result as performing it only once. "
                              "@type: bool")
    parameters = Attribute("List of action parameters. "
                           "@type: list of IActionParam")
    result_info = Attribute("Information about action's result or None "
                            "if the action do not return any result. "
                            "@type: IValueInfo or None")

    def initiate(aspect=None):
        """
        Initiates the action with specified aspect.
        @param aspect: the action aspect.
        @type aspect: IAspect or None
        @return a deferred fired with the action itself.
        @rtype: defer.Deferred
        @callback: IModelAction
        """

    def perform(**kwargs):
        """
        Performs the action with specified keyword arguments.
        If the action was done successfully, the deferred is fired
        with a value of any type or None. The value could be a model
        itself and most probably a IResponseModel providing more
        information about the outcome of the action alongside the data.
        If the model will perform the action later or it is not finished
        yet it could return a IResponse with response type "accepted".
        @param kwargs: the action arguments.
        @type kwargs: dict()
        @return: a deferred fired with the action result or None.
        @rtype: defer.Deferred
        @callback: object or None
        @errback TransientError: if the action couldn't be performed for
                                 unexpected reasons but the operation could
                                 be retried later.
        @errback Unauthorized: if the the caller is not authorized
                               to perform the action.
        @errback NotAvailable: if the model source is not available
                               or the action is not enabled.
        @errback ParameterError: if an action parameter is missing, wrong
                                 or an unknown parameter was specified.
        @errback ActionFailed: if the action failed in any ways.
        """


class IActionParam(Interface):
    """Action parameter descriptor."""

    name = Attribute("Parameter name unique for all action's parameters. "
                     "@type: unicode")
    label = Attribute("Parameter label or None. @type: unicode or None")
    desc = Attribute("Parameter description or None. @type: unicode or None")
    value_info = Attribute("Information about the parameter value. "
                           "@type: IValueInfo")
    is_required = Attribute("If the parameter is required or optional. "
                            "@type: bool")


class IActionPayload(Interface):
    """
    Interface identifying an object received containing action parameters.
    to be used when registering document readers.
    instance implementing this interface should provide
    the dictionary protocol.
    """


class IErrorPayload(Interface):
    """Interface identifying a generic error object."""

    error_type = Attribute("Error type. @type: ErrorTypes")
    error_code = Attribute("Error number. @type: int or None")
    message = Attribute("Short error message. @type: unicode or None")
    subjects = Attribute("Subject of the error, what causes the error. "
                        "@type: list of unicode or None")
    reasons = Attribute("Reasons of the errors, optional dictionary indexed "
                        "by a subject describing the reason why it failed "
                        "@type: {unicode(): unicode()}")
    debug = Attribute("Debugging information. @type: unicode or None")
    trace = Attribute("Debugging trace. @type: unicode or None")
    stamp = Attribute("Debugging stamp. @type; unicode or None")


### private interfaces ###


class IValidator(Interface):

    def validate(value):
        """
        Validates the specified value.
        It will try to convert the value if not in the expected type.
        object extra constraints provided by other interfaces are enforced too.
        @param value: value to be validated and converted.
        @type value: object
        @return: a validated value of expected type.
        @rtype: object
        @raise ValueError: if the value fail the validation.
        """

    def publish(value):
        """
        Publish the specified value.
        This will eventually convert the value to a public format
        the validate method will be able to  understand
        and convert back to the internal format.
        @param value: value to be published and converted.
        @type value: object
        @return: a published value.
        @rtype: object
        @raise ValueError: if the value is not correct.
        """

    def as_string(value):
        """Returns the value as a unicode string validate() understands."""


class IAspect(Interface):
    """Aspect of a model or an action defined by its owner."""

    name = Attribute("Aspect name. @type: unicode")
    label = Attribute("Aspect label. @type: unicode or None")
    desc = Attribute("Aspect description. @type: unicode or None")


class IModelFactory(Interface):

    def __call__(source, aspect=None, view=None, parent=None, officer=None):
        """
        Creates a model instance for the specified source reference.
        @param source: the source the model should reference.
        @type source: object
        @param aspect: the model aspect.
        @type aspect: IAspect
        @param view: if the mode is a view, contains view value.
        @type view: object()
        @param parent: the parent model if known.
        @type parent: IModel or None
        @param officer: the officer controlling the model accesses.
        @type officer: IOfficer or None
        @return: a model for the given source and aspect.
        @rtype: IModel
        """


class IActionFactory(Interface):

    def __call__(model):
        """
        Creates an action instance for the specified model.
        @param model: the model the action should be created for.
        @type model: IModel
        @return: an action for the given model and aspect.
        @rtype: IModelAction
        """


class IContextMaker(Interface):

    def make_context(key=None, view=None, action=None):
        """
        Create a context dictionary, some value can be overridden.
        @param key: overridden value for key.
        @type key: str or unicode or None
        @param view: overridden value for view.
        @type view: object() or None
        @param action: overridden value for action.
        @type action: IModelAction or None
        @return: a context dictionary
        @rtype: dict
        """
