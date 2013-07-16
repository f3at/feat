import sys

from zope.interface import adapter, interface, declarations, implements

from feat.common import serialization, reflect, log, registry, error
from feat.models import model

from feat.interface.agent import IAgentFactory, IDescriptor
from feat.database.interface import IViewFactory, IDocument, IMigration
from feat.interface.application import IApplication


def load(module_name, name):
    log.info('application', "Importing application %s from module %s",
             name, module_name)
    module = sys.modules.get(module_name)
    if module:
        log.warning('application',
                    "Application module %s has already been loaded. ",
                    module_name)
    else:
        module = reflect.named_module(module_name)
    application = getattr(module, name, None)
    if application is None:
        raise ValueError('Module %s has no attribute %s' % (module_name, name))
    if not IApplication.providedBy(application):
        raise ValueError('Variable %s.%s should provide IApplication interface'
                         % (module_name, name))
    try:
        application.load()
    except Exception as e:
        error.handle_exception(
            'application', e, 'Error loading application: %s',
            application.name)
        application.unload()
        raise
    else:
        get_application_registry().register(application)
        log.info('application', "Loading application %s complete.", name)


def unload(name):
    log.info('application', "Starting unloading application %r", name)
    r = get_application_registry()
    application = r.lookup(name)
    if not application:
        log.error("application", "Tried to unload application which is not "
                  "loaded: %r", name)
        return
    try:
        application.unload()
    except Exception as e:
        error.handle_exception('application', e, "Problem while unloading "
                               "application %r", name)
    log.info('application', "Unloading application %r complete", name)


class Application(log.Logger):
    implements(IApplication)

    log_category = 'application'
    name = None
    version = 1
    module_prefixes = []
    loadlist = []

    def __init__(self):
        self.log_name = self.name
        self.module = self.__module__
        log.Logger.__init__(self, log.get_default())
        self._restorators = serialization.get_registry()
        self._agents = get_agent_registry()
        self._views = get_view_registry()
        self._initial_data = get_initial_data_registry()
        self._adapters = adapter.AdapterRegistry()
        self._models = model.get_registry()

        # (version, IMigration)
        self._migrations = list()

    def load(self):
        self.info("Loading application %s", self.name)
        for module in self.loadlist:
            self.debug("Importing module %s", module)
            if module in sys.modules:
                self.warning("Module %s is already available in sys.modules.",
                             module)
            else:
                reflect.named_module(module)

        self.load_adapters()

    def load_adapters(self):
        if self._adapter_hook in interface.adapter_hooks:
            self.warning("Adapter hook has already been present")
        else:
            interface.adapter_hooks.append(self._adapter_hook)

    def unload_adapters(self):
        try:
            interface.adapter_hooks.remove(self._adapter_hook)
        except ValueError:
            self.warning("Adapter hook has not been present")

    def unload(self):
        self.info("Unloading application %s", self.name)
        self._restorators.application_cleanup(self)
        self._agents.application_cleanup(self)
        self._views.application_cleanup(self)
        self._initial_data.application_cleanup(self)
        self._models.application_cleanup(self)
        self.unload_adapters()
        del(self._adapters)

        for canonical_name, module in sys.modules.items():
            if not self._should_be_unloaded(canonical_name):
                continue
            self.info("Removing module %s from sys.modules", canonical_name)
            m = sys.modules[canonical_name]
            del(sys.modules[canonical_name])
            del(m)

    def register_restorator(self, restorator, type_name=None):
        self._restorators.register(restorator, application=self,
                                   key=type_name)
        return restorator

    def register_descriptor(self, name):

        def register_descriptor(klass):
            klass.type_name = name
            return self.register_restorator(klass)

        return register_descriptor

    def register_agent(self, name, configuration_id=None):

        def register_agent(klass):
            self._agents.register(klass, key=name, application=self)
            doc_id = configuration_id or name + "_conf"
            klass.application = self
            klass.descriptor_type = name
            klass.type_name = name + ":data"
            klass.configuration_doc_id = doc_id
            klass.application.register_restorator(klass)
            return klass

        return register_agent

    def register_adapter(self, adapted, *interfaces):

        def register_adapter(adapter_factory):
            assert interfaces, "You need to pass an Interface"

            # deal with class->interface adapters:
            if not isinstance(adapted, interface.InterfaceClass):
                adapted_ = declarations.implementedBy(adapted)
            else:
                adapted_ = adapted

            for iface in interfaces:
                factory = self._adapters.registered([adapted_], iface)
                if factory is not None:
                    raise ValueError("an adapter (%s) was already registered."
                                     % (factory, ))
            for iface in interfaces:
                self._adapters.register([adapted_], iface, '', adapter_factory)

            return adapter_factory

        return register_adapter

    def register_view(self, klass):
        if klass.design_doc_id == 'feat':
            # don't override the design document name if it has been set
            # to something nondefault
            klass.design_doc_id = unicode(self.name)
        self._views.register(klass, application=self)
        return klass

    def register_model(self, klass):
        self._models.register(klass, application=self)
        return klass

    def initial_data(self, doc):
        if callable(doc) and IDocument.implementedBy(doc):
            doc = doc()
        doc = IDocument(doc)
        if doc.doc_id is None:
            raise ValueError(
                "Initial documents should have doc_id fixed (None)")
        self._initial_data.register(doc, application=self)
        return doc

    def register_migration(self, version, migration):
        migration = IMigration(migration)
        self._migrations.append((version, migration))

    def get_migrations(self):
        return list(self._migrations)

    ### private ###

    def _should_be_unloaded(self, canonical_name):
        for prefix in self.module_prefixes:
            if canonical_name.startswith(prefix):
                return True

    def _adapter_hook(self, iface, ob):
        factory = self._adapters.lookup1(declarations.providedBy(ob), iface)
        return factory and factory(ob)


### registry of loaded applications ###


class ApplicationRegistry(registry.BaseRegistry):

    allow_blank_application = True
    verify_interface = IApplication
    key_attribute = 'name'


_application_registry = ApplicationRegistry()


def get_application_registry():
    global _application_registry
    return _application_registry


### registry of agent factories ###


class AgentRegistry(registry.BaseRegistry):

    allow_blank_application = False
    verify_interface = IAgentFactory


_agent_registry = AgentRegistry()


def get_agent_registry():
    global _agent_registry
    return _agent_registry


def lookup_agent(name):
    global _agent_registry
    return _agent_registry.lookup(name)


def lookup_descriptor(name):
    r = serialization.lookup(name)
    if r is not None and not IDescriptor.implementedBy(r):
        raise TypeError("lookup_descriptor() tried to return %r" % (r, ))
    return r


### registry of view factories ###


class ViewRegistry(registry.BaseRegistry):

    allow_blank_application = False
    allow_none_key = False
    verify_interface = IViewFactory
    key_attribute = 'name'


_view_registry = ViewRegistry()


def get_view_registry():
    global _view_registry
    return _view_registry


### registry of initial documents ###


class InitialDataRegistry(registry.BaseRegistry):

    allow_blank_application = False
    verify_interface = IDocument
    key_attribute = 'doc_id'


_initial_data_registry = InitialDataRegistry()


def get_initial_data_registry():
    global _initial_data_registry
    return _initial_data_registry
