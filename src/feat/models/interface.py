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

__all__ = ["ResponseTypes", "ActionCategory", "ValueTypes",
           "ModelError", "TransientError", "BadReference",
           "NotSupported", "Unauthorized", "NotAvailable",
           "ActionFailed", "ActionConflict",
           "IMetadata", "IMetadataItem",
           "IContext", "IReference", "IRelativeReference",
           "ILocalReference", "IAbsoluteReference",
           "IModel", "IAttribute", "IResponse",
           "IModelItem", "IModelAction", "IActionParam",
           "IValueInfo", "IValueCollection", "IValueRange",
           "IValueOptions", "IValueOption"]


class ResponseTypes(enum.Enum):
    """
    Types of success response model that an action could return:
     - done: The action has been done successfully.
     - created: The action resulted in a new model being created successfully.
     - accepted: The action has been accepted
                 but it is not started yet or not finished yet.
     """
    done, created, accepted = range(3)


class ActionCategory(enum.Enum):
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
     - model: a response model.
     - integer: an integer value.
     - number: an integer or a float
     - boolean: True or False
     - string: a unicode string
     - collection: a collection of other value.
     - binary: a binary blob.
    """
    model, integer, number, boolean, string, collection, binary = range(7)


class ModelError(error.FeatError):
    """Base exception for model related errors."""


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


class IValueCollection(IValueInfo):
    """Define a collection of values."""

    allowed_types = Attribute("Allowed sub types. @type: list of IValueInfo")
    is_ordered = Attribute("If the list order is important. @type: bool")
    allow_multiple = Attribute("If the same value is allowed multiple times. "
                               "@type: bool")


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

    def make_address(self, location):
        """Make and address from a tuple resolved but a reference."""


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

    def fetch():
        """
        Tries to fetch the referenced model.
        Could fail if the model backend do not support it,
        for example it may only work for local reference.
        @return: a deferred fired with the reference model.
        @rtype: defer.Deferred
        @callback: IModel
        @errback TransientError: if the model couldn't be fetched
                                 but the operation could be retried later.
        @errback Unauthorized: if the the caller is not authorized
                               to retrieve the referenced model.
        @errback NotAvailable: if the referenced model is not available.
        @errback NotSupported: if the model backend do not support
                               fetching this reference.
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

    def query_items(**kwargs):
        """
        #FIXME: Not fully defined yet.
        @return: a deferred fired with a subset of the model's items
                 filtered following the specified parameters.
        @rtype: defer.Deferred
        @callback: list of IModelItem
        @errback TransientError: if items couldn't be fetched for unexpected
                                 reasons, but it could be retried later.
        @errback Unauthorized: if the the caller is not authorized
                               to perform the query.
        @errback NotAvailable: if the model source is not available.
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

    def perform_action(name, *args, **kwargs):
        '''
        Fetch action and perform it passing arguments and keywords.
        @callback: return value of the action
        @errback AttributeError: if the action does not exist
        '''


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
    reference = Attribute("Reference to the model. @type: IReference")

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
    label = Attribute("Action short label. @type: unicode or None")
    desc = Attribute("Action long description. @type: unicode or None")
    category = Attribute("Action category. @type: ActionCategories")
    is_idempotent = Attribute("If performing the action multiple times gives "
                              "the same result as performing it only once. "
                              "@type: bool")
    value_info = Attribute("Information about the action value or None "
                           "if the action do not require any value. "
                           "@type IValueInfo or None")
    parameters = Attribute("List of action parameters. "
                           "@type: list of IActionParam")
    result_info = Attribute("Information about action's result or None "
                            "if the action do not return any result. "
                            "@type: IValueInfo or None")

    def perform(*args, **kwargs):
        """
        Performs the action with specified value and parameters.
        If value is needed it MUST be the first argument,
        and all parameters MUST be keywords.
        If the action was done successfully, the deferred is fired
        with a value of any type or None. The value could be a model
        itself and most probably a IResponseModel providing more
        information about the outcome of the action alongside the data.
        If the model will perform the action later or it is not finished
        yet it could return a IResponse with response type "accepted".
        @param value: the action value if required nothing if not.
        @type value: object
        @return: a deferred fired with the action result or None.
        @rtype: defer.Deferred
        @callback: object
        @errback TransientError: if the action couldn't be performed for
                                 unexpected reasons but the operation could
                                 be retried later.
        @errback Unauthorized: if the the caller is not authorized
                               to perform the action.
        @errback NotAvailable: if the model source is not available
                               or the action is not enabled.
        @errback ValueError: if the action value or parameters are wrong.
        @errback TypeError: if the value or a parameter is missing
                            or an unknown parameter was specified.
        @errback ActionFailed: if the action failed in any ways.
        """


class IActionParam(Interface):
    """Action parameter descriptor."""

    name = Attribute("Parameter name unique for all action's parameters. "
                     "@type: ascii encoded string")
    label = Attribute("Parameter label or None. @type: unicode or None")
    desc = Attribute("Parameter description or None. @type: unicode or None")
    info = Attribute("Information about the parameter value. "
                     "@type: IValueInfo")
    is_required = Attribute("If the parameter is required or optional. "
                            "@type: bool")


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


class IAspect(Interface):
    """Aspect of a model or an action defined by its owner."""

    name = Attribute("Aspect name. @type: unicode")
    label = Attribute("Aspect label. @type: unicode or None")
    desc = Attribute("Aspect description. @type: unicode or None")


class IModelFactory(Interface):

    def __call__(source, aspect=None, view=None):
        """
        Creates a model instance for the specified source reference.
        @param source: the source the model should reference.
        @type source: object
        @param aspect: the model aspect.
        @type aspect: IAspect
        @param view: if the mode is a view, contains view value.
        @type view: object()
        @return: a model for the given source and aspect.
        @rtype: IModel
        """


class IActionFactory(Interface):

    def __call__(model, aspect=None):
        """
        Creates an action instance for the specified model.
        @param model: the model the action should be created for.
        @type model: IModel
        @param aspect: the action aspect.
        @type aspect: IAspect
        @return: an action for the given model and aspect.
        @rtype: IModelAction
        """
