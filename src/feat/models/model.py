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

import types

from zope.interface import implements

from feat.common import error, annotate, container, defer, error
from feat.models import utils
from feat.models import meta as models_meta
from feat.models import reference as models_reference

from feat.models.interface import IModel, IModelItem, NotSupported
from feat.models.interface import IActionFactory, IModelFactory
from feat.models.interface import IAspect, IReference


### Annotations ###


meta = models_meta.meta


def identity(identity):
    """
    Annotates the identity of the model being defined.
    @param identity: model unique identity
    @type identity: str or unicode
    """
    _annotate("identity", identity)


def attribute(name, value, getter=None, setter=None,
              label=None, desc=None, meta=None):
    """
    Annotates a model attribute.
    @param name: attribute name, unique for a model.
    @type name: str or unicode
    @param value: attribute type information.
    @type value: IValueInfo
    @param getter: an effect or None if the attribute is write-only;
                   the retrieved value that will be validated;
                   see feat.models.call for effect information.
    @type getter: callable or None
    @param setter: an effect or None if the attribute is read-only;
                   the new value will be validated, possibly converted
                   and returned;
                   see feat.models.call for effect information.
    @type setter: callable or None
    @param label: the attribute label or None.
    @type label: str or unicode or None
    @parama desc: the description of the attribute or None if not documented.
    @type desc: str or unicode or None
    """
    _annotate("attribute", name, value, getter=getter, setter=setter,
              label=label, desc=desc, meta=meta)


def child(name, getter=None, model=None, label=None, desc=None):
    """
    Annotate a sub-model to the one being defined.
    @param name: item name unique for the model being defined.
    @type name: str or unicode
    @param getter: an effect to retrieve the sub-model source
                   or None to use the same source;
                   see feat.models.call for effect information.
    @type getter: callable or None
    @param model: the model identity or model factory to use,
                  or None to use IModel adapter.
    @type model: str or unicode or IModelFactory or None
    @param label: the sub-model label or None.
    @type label: str or unicode or None
    @parama desc: the description of the sub-model or None if not documented.
    @type desc: str or unicode or None
    """
    _annotate("child", name, getter=getter, model=model,
              label=label, desc=desc)


def view(name, model, value=None, label=None, desc=None, meta=None):
    """
    Annotate a sub-view to the one being defined.
    A view is another model with the same source
    and a view value retrieved from the specifed getter.
    @param name: item name unique for the model being defined.
    @type name: str or unicode
    @param model: the model identity or model factory to use.
    @type model: str or unicode or IModelFactory or None
    @param value: view value or an effect to retrieve it;
                  see feat.models.call for effect information.
    @type value: callable or object()
    @param label: the sub-model label or None.
    @type label: str or unicode or None
    @parama desc: the description of the sub-model or None if not documented.
    @type desc: str or unicode or None
    """
    _annotate("view", name, model=model, value=value,
              label=label, desc=desc, meta=meta)


def reference(*args, **kwargs):
    raise NotImplementedError("model.reference() is not implemented yet")


def command():
    raise NotImplementedError("model.command() is not implemented yet")


def create():
    raise NotImplementedError("model.create() is not implemented yet")


def put():
    raise NotImplementedError("model.put() is not implemented yet")


def update():
    raise NotImplementedError("model.update() is not implemented yet")


def delete():
    raise NotImplementedError("model.delete() is not implemented yet")


def action(name, factory, label=None, desc=None):
    """
    Annotate a model's action.
    @param name: the name of the model's action.
    @type name: str or unicode
    @param factory: a factory to create actions.
    @type factory: IActionFactory
    @param label: the action label if specified.
    @type label: str or unicode or None
    @param desc: the action description if specified.
    @type desc: str or unicode or None
    """
    _annotate("action", name, factory,
              label=label, desc=desc)


def children(name, child_source, child_names=None,
             child_model=None, child_label=None, child_desc=None,
             label=None, desc=None, meta=None):
    """
    Annotate a dynamic collection of sub-models.
    @param name: the name of the collection model containing the sub-models.
    @type name: str or unicode
    @param child_source: an effect that retrieve a sub-model source from
                         a sub-model name.
    @type child_source: callable
    @param child_names: an effect that retrieve all sub-models names or
                        None if sub-models are not iterable.
    @type child_source: callable
    @param child_model: the model identity or model factory to use for
                        sub-models, or None to use IModel adapter.
    @type child_model: str or unicode or IModelFactory or None
    @param child_label: the model items label or None.
    @type child_label: str or unicode or None
    @param child_desc: the model items description or None.
    @type child_desc: str or unicode or None
    @param label: the collection label or None.
    @type label: str or unicode or None
    @param desc: the collection description or None.
    @type desc: str or unicode or None
    """
    _annotate("children", name, child_source=child_source,
              child_names=child_names, child_model=child_model,
              child_label=child_label, child_desc=child_desc,
              label=label, desc=desc, meta=meta)


def child_names(effect):
    """
    Annotate the effect used to retrieve the model's children names.
    @param effect: an effect to retrieve the names.
    @type effect: callable
    """
    _annotate("child_names", effect)


def child_source(effect, model=None, label=None, desc=None):
    """
    Annotate the effect used to retrieve a sub-model's source by name.
    @param effect: an effect to retrieve a source from name.
    @type effect: callable
    @param model: the model identity or model factory to use,
                  or None to use IModel adapter.
    @type model: str or unicode or IModelFactory or None
    @param label: the model items label or None.
    @type label: str or unicode or None
    @param desc: the model items description or None.
    @type desc: str or unicode or None
    """
    _annotate("child_source", effect, model=model, label=label, desc=desc)


def _annotate(name, *args, **kwargs):
    method_name = "annotate_" + name
    annotate.injectClassCallback(name, 4, method_name, *args, **kwargs)


### Registry ###


def register_factory(identity, factory):
    global _model_factories
    identity = unicode(identity)
    if identity in _model_factories:
        raise KeyError("Factory already registered for %s: %r"
                       % (identity, _model_factories[identity]))
    _model_factories[identity] = IModelFactory(factory)


def get_factory(identity):
    global _model_factories
    return _model_factories.get(unicode(identity))


def snapshot_factories():
    global _model_factories
    return dict(_model_factories)


def restore_factories(snapshot):
    global _model_factories
    _model_factories = dict(snapshot)


### Classes ###


class MetaModel(type(models_meta.Metadata)):
    implements(IModelFactory)


class AbstractModel(models_meta.Metadata):
    """
    Base class for models, it DOES NOT IMPLEMENTE IModel.
    All what define models are defined at class level,
    instance only hold a reference to the source the model
    applies on and an aspect defined by its parent model.
    """

    __metaclass__ = MetaModel
    __slots__ = ("source", "aspect", "view")

    implements(IModel)

    _identity = None

    def __init__(self, source, aspect=None, view=None):
        self.source = source
        self.aspect = IAspect(aspect) if aspect is not None else None
        self.view = view

    ### public ###

    @property
    def name(self):
        return self.aspect.name if self.aspect is not None else None

    @property
    def label(self):
        return self.aspect.label if self.aspect is not None else None

    @property
    def desc(self):
        return self.aspect.desc if self.aspect is not None else None

    ### IModel ###

    @property
    def identity(self):
        return self._identity

    def perform_action(self, name, **kwargs):
        d = self.fetch_action(name)
        d.addCallback(defer.call_param, 'perform', **kwargs)
        return d

    # provides_item() should be implemented by sub-classes

    # count_items() should be implemented by sub-classes

    # fetch_item() should be implemented by sub-classes

    # fetch_items() should be implemented by sub-classes

    # query_items() should be implemented by sub-classes

    # provides_action() should be implemented by sub-classes

    # count_actions() should be implemented by sub-classes

    # fetch_action() should be implemented by sub-classes

    # fetch_actions() should be implemented by sub-classes

    ### annotations ###

    @classmethod
    def annotate_identity(cls, identity):
        """@see: feat.models.model.identity"""
        cls._identity = _validate_str(identity)
        register_factory(cls._identity, cls)


class NoChildrenMixin(object):
    """Mix with BaseModel for models without sub-model."""

    __slots__ = ()

    ### IModel ###

    def provides_item(self, name):
        return defer.succeed(False)

    def count_items(self):
        return defer.succeed(0)

    def fetch_item(self, name):
        return defer.succeed(None)

    def fetch_items(self):
        return defer.succeed(iter([]))

    def query_items(self, **kwargs):
        return defer.fail(NotSupported("Model do not support item queries"))


class NoActionsMixin(object):
    """Mix with BaseModel for models without actions."""

    __slots__ = ()

    ### IModel ###

    def provides_action(self, name):
        return defer.succeed(False)

    def count_actions(self):
        return defer.succeed(0)

    def fetch_action(self, name):
        return defer.succeed(None)

    def fetch_actions(self):
        return defer.succeed(iter([]))


class EmptyModel(AbstractModel, NoChildrenMixin, NoActionsMixin):
    """A model without any items or actions."""

    __slots__ = ()


class StaticChildrenMixin(object):

    _model_items = container.MroDict("_mro_model_items")

    __slots__ = ()

    ### IModel ###

    def provides_item(self, name):

        def check_initiated(model_item):
            # a model item is provided if its initiate method
            # returns a none None value
            return model_item is not None

        def log_error(failure):
            error.handle_failure(None, failure, "Error checking if %s "
                                 "model %s is providing %s",
                                 self.identity, self.name, name)
            return None

        item = self._model_items.get(name)
        if item is not None:
            d = item(self).initiate()
            d.addCallbacks(check_initiated, log_error)
            return d

        return defer.succeed(False)

    def count_items(self):

        def log_error(failure):
            error.handle_failure(None, failure, "Error counting %s model "
                                 "%s items", self.identity, self.name)
            return None

        def count_items(items):
            # Only count the model items whose initiate method
            # returns a non None value
            return len(filter(None, items))

        items = [i(self).initiate().addErrback(log_error)
                 for i in self._model_items.itervalues()]
        d = defer.join(*items) # Errors are ignored
        d.addCallback(count_items)
        return d

    def fetch_item(self, name):

        def log_error(failure):
            error.handle_failure(None, failure, "Error fetching %s model "
                                 "%s item %s", self.identity, self.name, name)
            return None

        item = self._model_items.get(name)
        if item is not None:
            return item(self).initiate().addErrback(log_error)

        return defer.succeed(None)

    def fetch_items(self):

        def log_error(failure):
            error.handle_failure(None, failure, "Error fetching %s model "
                                 "%s items", self.identity, self.name)
            return None

        def cleanup(items):
            # Only return model items whose initiate method
            # returns a non None value
            return filter(None, items)

        items = [item(self).initiate().addErrback(log_error)
                 for item in self._model_items.itervalues()]
        d = defer.join(*items)
        d.addCallback(cleanup)
        return d

    def query_items(self, **kwargs):
        return defer.fail(NotSupported("%s model %s do not support "
                                       "item queries" % (self.identity,
                                                         self.name)))

    ### annotations ###

    @classmethod
    def annotate_child(cls, name, getter, model=None, label=None, desc=None,
                       meta=None):
        """@see: feat.models.model.child"""
        name = _validate_str(name)
        item = MetaModelItem.new(name, fetcher=getter, browser=getter,
                                 factory=model, label=label, desc=desc)
        if meta:
            for decl in meta:
                item.annotate_meta(*decl)
        cls._model_items[name] = item

    @classmethod
    def annotate_view(cls, name, model=None, value=None,
                      label=None, desc=None, meta=None):
        """@see: feat.models.model.view"""
        name = _validate_str(name)
        item = MetaModelItem.new(name, factory=model, view=value,
                                 label=label, desc=desc)
        if meta:
            for decl in meta:
                item.annotate_meta(*decl)
        cls._model_items[name] = item

    @classmethod
    def annotate_attribute(cls, name, value_info,
                           getter=None, setter=None,
                           label=None, desc=None, meta=None):
        """@see: feat.models.model.attribute"""
        from feat.models import attribute
        name = _validate_str(name)
        attr_ident = cls._identity + "." + name
        attr_cls = attribute.MetaAttribute.new(attr_ident, value_info,
                                               getter=getter, setter=setter)
        item = MetaModelItem.new(name, factory=attr_cls,
                                 label=label, desc=desc)
        item.annotate_meta('inline', True)
        if meta:
            for decl in meta:
                item.annotate_meta(*decl)
        cls._model_items[name] = item

    @classmethod
    def annotate_children(cls, name, child_source, child_names=None,
                        child_model=None, child_label=None, child_desc=None,
                        label=None, desc=None, meta=None):
        """@see: feat.models.model.children"""
        name = _validate_str(name)
        coll_cls = MetaCollection.new(cls._identity + "." + name,
                                      child_source=child_source,
                                      child_names=child_names,
                                      child_model=child_model,
                                      child_label=child_label,
                                      child_desc=child_desc)
        item = MetaModelItem.new(name, factory=coll_cls,
                                 label=label, desc=desc)
        if meta:
            for decl in meta:
                item.annotate_meta(*decl)

        cls._model_items[name] = item


class StaticActionsMixin(object):

    __slots__ = ()

    _action_items = container.MroDict("_mro_action_items")

    ### IModel ###

    def provides_action(self, name):

        def log_error(failure):
            error.handle_failure(None, failure, "Error checking if %s model "
                                 "%s provides action %s",
                                 self.identity, self.name, name)
            return None

        def check_initiated(action_item):
            # an action is provided only if the action item
            # initiate method returns a non None value
            return action_item is not None

        item = self._action_items.get(name)
        if item is not None:
            d = item(self).initiate().addErrback(log_error)
            d.addCallbacks(check_initiated)
            return d

        return defer.succeed(False)

    def count_actions(self):

        def log_error(failure):
            error.handle_failure(None, failure, "Error counting %s model "
                                 "%s actions", self.identity, self.name)
            return None

        def count_items(items):
            # Only count the action items whose initiate method
            # returns a non None value
            return len(filter(None, items))

        items = [i(self).initiate().addErrback(log_error)
                 for i in self._action_items.itervalues()]
        d = defer.join(*items) # Errors are ignored
        d.addCallback(count_items)
        return d

    def fetch_action(self, name):

        def log_error(failure):
            error.handle_failure(None, failure, "Error fetching %s model %s "
                                 "action %s", self.identity, self.name, name)
            return None

        def action_initiated(action_item):
            # Only fetch action whose item initiate method returns
            # a non None value
            if action_item is not None:
                return action_item.fetch()
            return None

        item = self._action_items.get(name)
        if item is not None:
            d = item(self).initiate().addErrback(log_error)
            d.addCallback(action_initiated)
            return d

        return defer.succeed(None)

    def fetch_actions(self):

        def log_error(failure):
            error.handle_failure(None, failure, "Error fetching %s model %s "
                                 "actions", self.identity, self.name)
            return None

        def item_initiated(action_item):
            # Only fetch action of items whose initiate method
            # returns a non None value
            if action_item is not None:
                return action_item.fetch()
            return None

        def cleanup(actions):
            # Cleanup actions whose action item's initiate method
            # did not returns a non None value
            return filter(None, actions)

        actions = [i(self).initiate().addCallbacks(item_initiated, log_error)
                   for i in self._action_items.itervalues()]
        d = defer.join(*actions)
        d.addCallback(cleanup)
        return d

    ### annotations ###

    @classmethod
    def annotate_action(cls, name, factory, label=None, desc=None):
        """@see: feat.models.model.action"""
        name = _validate_str(name)
        item = MetaActionItem.new(name, factory, label=label, desc=desc)
        cls._action_items[name] = item


class Model(AbstractModel, StaticChildrenMixin, StaticActionsMixin):
    """Static model with a known set of sub-models and actions."""

    __slots__ = ()


class BaseModelItem(models_meta.Metadata):

    __slots__ = ("model", )

    def __init__(self, model):
        self.model = model

    ### public ###

    def initiate(self):
        """If the returned deferred is fired with None,
        the item will be disabled as if did not exists."""
        return defer.succeed(self)

    ### virtual ###

    @property
    def name(self):
        """To be overridden by sub classes."""

    @property
    def aspect(self):
        """To be overridden by sub classes."""

    ### protected ###

    def _create_model(self, view_getter=None, source_getter=None,
                      model_factory=None):
        d = defer.succeed(None)
        d.addCallback(self._retrieve_view, view_getter)
        d.addCallback(self._got_view, source_getter, model_factory)
        return d

    def _retrieve_view(self, _param=None, view_getter=None):
        if callable(view_getter):
            context = {"model": self.model,
                       "view": self.model.view,
                       "key": self.name}
            return view_getter(None, context)

        if view_getter is None:
            # views are inherited
            return self.model.view

        return view_getter

    def _got_view(self, view, source_getter, model_factory):
        d = defer.succeed(view)
        d.addCallback(self._retrieve_source, source_getter)
        d.addCallback(self._wrap_source, view, model_factory)
        return d

    def _retrieve_source(self, view, source_getter=None):
        if source_getter is None:
            return self.model.source

        context = {"model": self.model,
                   "view": view,
                   "key": self.name}
        return source_getter(None, context)

    def _wrap_source(self, source, view=None, model_factory=None):
        if source is None:
            return source
        if IModel.providedBy(source):
            return source
        if IReference.providedBy(source):
            return source
        if IModelFactory.providedBy(model_factory):
            return model_factory(source, self.aspect, view)
        if isinstance(model_factory, str):
            factory = get_factory(model_factory)
            if factory is not None:
                return factory(source, self.aspect, view)
        return IModel(source) # No aspect, no view


class MetaModelItem(type(BaseModelItem)):

    implements(IAspect)

    @staticmethod
    def new(name, fetcher=None, browser=None,
            factory=None, view=None,
            label=None, desc=None):

        cls_name = utils.mk_class_name(name, "ModelItem")
        name = _validate_str(name)
        ref = models_reference.Relative(name)
        return MetaModelItem(cls_name, (ModelItem, ),
                             {"__slots__": (),
                              "_name": name,
                              "_reference": ref,
                              "_fetcher": _validate_effect(fetcher),
                              "_browser": _validate_effect(browser),
                              "_factory": _validate_model_factory(factory),
                              "_view": _validate_effect(view),
                              "_label": _validate_optstr(label),
                              "_desc": _validate_optstr(desc)})

    ### IAspect ###

    @property
    def name(cls):
        return cls._name

    @property
    def label(cls):
        return cls._label

    @property
    def desc(cls):
        return cls._desc


class ModelItem(BaseModelItem):

    __metaclass__ = MetaModelItem
    __slots__ = ()

    implements(IModelItem)

    _name = None
    _reference = None
    _fetcher = None
    _browser = None
    _view = None
    _factory = None
    _label = None
    _desc = None

    def __init__(self, model):
        BaseModelItem.__init__(self, model)

    ### public ###

    def initiate(self):
        """If the returned deferred is fired with None,
        the item will be disabled as if did not exists."""
        return defer.succeed(self)

    ### overridden ###

    @property
    def aspect(self):
        return type(self)

    ### IModelItem ###

    @property
    def name(self):
        return self._name

    @property
    def label(self):
        return self._label

    @property
    def desc(self):
        return self._desc

    @property
    def reference(self):
        return self._reference

    def browse(self):
        return self._create_model(self._view, self._browser, self._factory)

    def fetch(self):
        return self._create_model(self._view, self._fetcher, self._factory)


class MetaActionItem(type):

    implements(IAspect)

    @staticmethod
    def new(name, factory, label=None, desc=None):
        cls_name = utils.mk_class_name(name, "Action")
        return MetaActionItem(cls_name, (ActionItem, ),
                              {"__slots__": (),
                               "_name": _validate_str(name),
                               "_factory": _validate_action_factory(factory),
                               "_label": _validate_optstr(label),
                               "_desc": _validate_optstr(desc)})

    ### IAspect ###

    @property
    def name(cls):
        return cls._name

    @property
    def label(cls):
        return cls._label

    @property
    def desc(cls):
        return cls._desc


class ActionItem(object):

    __meta__ = MetaActionItem
    __slots__ = ("model", )

    _name = None
    _label = None
    _desc = None
    _factory = None

    def __init__(self, model):
        self.model = model

    def initiate(self):
        """If the returned deferred is fired with None,
        the action will be disabled as if did not exists."""
        return defer.succeed(self)

    ### public ###

    def fetch(self):
        return defer.succeed(self._factory(self.model, type(self)))


class DynamicItemsMixin(object):

    __slots__ = ()

    _fetch_names = None
    _fetch_source = None
    _item_label = None
    _item_desc = None

    ### IModel ###

    def provides_item(self, name):
        if self._fetch_source is None:
            return self._notsup("checking item availability")

        def log_error(failure):
            error.handle_failure(None, failure, "Error checking if %s model "
                                 "%s item %s is provided",
                                 self.identity, self.name, name)
            return None

        def cleanup(item):
            return item is not None

        item = DynamicModelItem(self, name)
        d = item.initiate().addErrback(log_error)
        d.addCallback(cleanup)
        return d

    def count_items(self):
        if self._fetch_names is None:
            return self._notsup("items counting")

        def log_error(failure):
            error.handle_failure(None, failure, "Error counting %s model %s "
                                 "items", self.identity, self.name)
            return None

        def create_items(names):
            Item = DynamicModelItem
            items = [Item(self, n).initiate().addErrback(log_error)
                     for n in names]
            return defer.join(*items)

        def cleanup(items):
            # Only counting the item whose initiate method
            # returns a non None value
            return len(filter(None, items))

        context = {"model": self,
                   "view": self.view,
                   "key": self.name}
        d = self._fetch_names(None, context)
        d.addCallback(create_items)
        d.addCallback(cleanup)
        return d

    def fetch_item(self, name):
        if self._fetch_source is None:
            return self._notsup("fetching item")

        def log_error(failure):
            error.handle_failure(None, failure, "Error fetching %s model %s "
                                 "item %s", self.identity, self.name, name)
            return None

        item = DynamicModelItem(self, name)
        return item.initiate().addErrback(log_error)

    def fetch_items(self):
        if self._fetch_names is None:
            return self._notsup("fetching items")

        def log_error(failure):
            error.handle_failure(None, failure, "Error fetching %s model %s "
                                 "items", self.identity, self.name)
            return None

        def create_items(names):
            Item = DynamicModelItem
            items = [Item(self, n).initiate().addErrback(log_error)
                     for n in names]
            return defer.join(*items)

        def cleanup(items):
            # Only returns the item whose initiate method
            # returns a non None value
            return filter(None, items)

        context = {"model": self,
                   "view": self.view,
                   "key": self.name}
        d = self._fetch_names(None, context)
        d.addCallback(create_items)
        d.addCallback(cleanup)
        return d

    def query_items(self, **kwargs):
        return self._notsup("querying items")

    ### private ###

    def _notsup(self, feature_desc):
        msg = ("%s model %s does not support %s"
               % (self.identity, self.name, feature_desc, ))
        return defer.fail(NotSupported(msg))

    ### annotations ###

    @classmethod
    def annotate_child_names(cls, effect):
        """@see: feat.models.collection.child_names"""
        cls._fetch_names = _validate_effect(effect)

    @classmethod
    def annotate_child_source(cls, effect, model=None, label=None, desc=None):
        """@see: feat.models.collection.child_source"""
        cls._fetch_source = _validate_effect(effect)
        cls._item_factory = _validate_model_factory(model)
        cls._item_label = _validate_optstr(label)
        cls._item_desc = _validate_optstr(desc)


class MetaCollection(type(AbstractModel)):

    @staticmethod
    def new(identity, child_source, child_names=None,
            child_model=None, child_label=None, child_desc=None):
        cls_name = utils.mk_class_name(identity)
        cls = MetaCollection(cls_name, (Collection, ), {"__slots__": ()})
        cls.annotate_identity(identity)
        cls.annotate_child_names(child_names)
        cls.annotate_child_source(child_source, model=child_model,
                                  label=child_label, desc=child_desc)
        return cls


class Collection(AbstractModel, StaticActionsMixin, DynamicItemsMixin):
    """
    A model with a static list of actions
    and a dynamic set of sub-models."""

    __metaclass__ = MetaCollection
    __slots__ = ()


class DynamicModelItem(BaseModelItem):

    __slots__ = ("_name", "_reference", "_child")

    implements(IModelItem, IAspect)

    def __init__(self, model, name):
        BaseModelItem.__init__(self, model)
        self._name = name
        self._reference = models_reference.Relative(name)
        self._child = None

    ### overridden ###

    @property
    def aspect(self):
        return self

    def initiate(self):
        # We need to do it right away to be sure the source exists
        d = self._create_model(source_getter=self.model._fetch_source,
                               model_factory=self.model._item_factory)
        d.addCallback(self._got_model)
        return d

    ### IModelItem / IAspect ###

    @property
    def name(self):
        return self._name

    @property
    def label(self):
        return self.model._item_label

    @property
    def desc(self):
        return self.model._item_desc

    @property
    def reference(self):
        return self._reference

    ### IModelItem ###

    def browse(self):
        return self._child

    def fetch(self):
        return self._child

    ### private ###

    def _got_model(self, model):
        if model is None:
            return None
        self._child = model
        return self


### private ###


_model_factories = {}


def _validate_str(value):
    return unicode(value)


def _validate_optstr(value):
    return unicode(value) if value is not None else None


def _validate_model_factory(factory):
    if factory is not None:
        if not isinstance(factory, str):
            return IModelFactory(factory)
    return factory


def _validate_action_factory(factory):
    return IActionFactory(factory)


def _validate_effect(effect):
    if isinstance(effect, types.FunctionType):
        return staticmethod(effect)
    return effect
