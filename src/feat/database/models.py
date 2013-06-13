from zope.interface import implements

from feat.common import annotate, defer
from feat.database import query
from feat.models import model, action, value, utils, call, effect

from feat.database.interface import IQueryViewFactory, IDatabaseClient
from feat.models.interface import IContextMaker, ActionCategories
from feat.models.interface import IValueOptions, ValueTypes


def db_connection(effect):
    annotate.injectClassCallback("db_connection", 3, "annotate_db_connection",
                                 effect)


def query_target(target):
    annotate.injectClassCallback("query_target", 3, "annotate_query_target",
                                 target)


def view_factory(factory, allowed_fields=[], static_conditions=None,
                 fetch_documents=None, item_field=None, include_value=list()):
    annotate.injectClassCallback(
        "view_factory", 3, "annotate_view_factory",
        factory, allowed_fields=allowed_fields,
        static_conditions=static_conditions,
        fetch_documents=fetch_documents,
        include_value=include_value,
        item_field=item_field)


class QueryView(model.Collection):

    _query_target = None
    _query_model = None
    _connection_getter = None
    _view = None

    @classmethod
    def __class__init__(cls, name, bases, dct):
        cls._query_set_factory = None

    def init(self):
        if not callable(type(self)._connection_getter):
            raise ValueError("This model needs to be annotated with "
                             "db_connection(effect) annotation")
        if type(self)._view is None:
            raise ValueError("This model needs to be annotated with "
                             "view_factory(IQueryViewFactory)")

        if type(self)._query_target is None:
            raise ValueError("This model needs to be annotated with "
                             "query_target(source|view)")

        context = IContextMaker(self).make_context()
        d = self._connection_getter(None, context)
        d.addCallback(self._set_connection)
        return d

    ### private ###

    def _set_connection(self, connection):
        self.connection = IDatabaseClient(connection)

    ### action body implementation ###

    def do_select(self, value, skip, sorting=None, limit=None):
        if sorting:
            value.set_sorting(sorting)
        cls = type(self)
        if cls._fetch_documents_set:
            method = query.select_ids
        else:
            method = query.select
        return method(self.connection, value, skip, limit)

    def render_select_response(self, value):
        cls = type(self)
        if not cls._query_set_factory:
            # query set collection is created only once per class type
            factory = model.MetaQuerySetCollection.new(type(self))
            factory.annotate_meta('json', 'render-as-list')
            cls._query_set_factory = factory
        items = [(self.get_child_name(x), x) for x in value]
        result = cls._query_set_factory(self.source, items)
        return result.initiate(view=self.view, officer=self.officer,
                               aspect=self.aspect)

    def do_count(self, value):
        return query.count(self.connection, value)

    def get_child_name(self, child):
        '''override in subclass if the result of your query is more complex
        than just a simple documents.'''
        return child.doc_id

    ### annotations ###

    @classmethod
    def annotate_query_target(cls, target):
        if target not in ['view', 'source']:
            raise ValueError('%s should be view or source' % (target, ))
        cls._query_target = target

    @classmethod
    def annotate_query_model(cls, query_model):
        cls._query_model = model._validate_model_factory(query_model)

    @classmethod
    def annotate_db_connection(cls, effect):
        cls._connection_getter = model._validate_effect(effect)

    @classmethod
    def annotate_view_factory(cls, factory, allowed_fields=[],
                              static_conditions=None,
                              fetch_documents=None,
                              include_value=list(),
                              item_field=None):
        cls._view = IQueryViewFactory(factory)
        cls._static_conditions = (static_conditions and
                                  model._validate_effect(static_conditions))
        if not fetch_documents:
            cls._fetch_documents_set = False
            fetch_documents = effect.identity
        else:
            cls._fetch_documents_set = True
            fetch_documents = fetch_documents

        for x in allowed_fields:
            if not cls._view.has_field(x):
                raise ValueError("%r doesn't define a field: '%s'" % (cls, x))
        cls._allowed_fields = allowed_fields

        for x in include_value:
            if not cls._view.has_field(x):
                raise ValueError("%r doesn't define a field: '%s'" % (cls, x))
        cls._include_value = include_value

        # define query action
        name = utils.mk_class_name(cls._view.name, "Query")
        QueryValue = MetaQueryValue.new(name, cls._view, cls._allowed_fields,
                                        cls._include_value)
        name = utils.mk_class_name(cls._view.name, "Sorting")
        SortingValue = MetaSortingValue.new(name, cls._allowed_fields)
        result_info = value.Model()

        def build_query(value, context, *args, **kwargs):

            def merge_conditions(static_conditions, factory, q):
                subquery = query.Query(factory, *static_conditions)
                return query.Query(factory, q, query.Operator.AND, subquery,
                                   include_value=cls._include_value)

            cls = type(context['model'])
            if cls._static_conditions:
                d = cls._static_conditions(None, context)
                d.addCallback(merge_conditions, cls._view, kwargs['query'])
                return d
            return defer.succeed(kwargs['query'])

        SelectAction = action.MetaAction.new(
            utils.mk_class_name(cls._view.name, "Select"),
            ActionCategories.retrieve,
            is_idempotent=False, result_info=result_info,
            effects=[
                build_query,
                call.model_perform('do_select'),
                fetch_documents,
                call.model_filter('render_select_response')],
            params=[action.Param('query', QueryValue()),
                    action.Param('sorting', SortingValue(), is_required=False),
                    action.Param('skip', value.Integer(0), is_required=False),
                    action.Param('limit', value.Integer(), is_required=False)])
        cls.annotate_action(u"select", SelectAction)

        # define count action
        CountAction = action.MetaAction.new(
            utils.mk_class_name(cls._view.name, "Count"),
            ActionCategories.retrieve,
            effects=[
                build_query,
                call.model_perform('do_count')],
            result_info=value.Integer(),
            is_idempotent=False,
            params=[action.Param('query', QueryValue())])
        cls.annotate_action(u"count", CountAction)

        # define how to fetch items
        if item_field:
            if not cls._view.has_field(item_field):
                raise ValueError("%r doesn't define a field: '%s'" %
                                 (cls, item_field))

            def fetch_names(value, context):
                model = context['model']
                d = build_query(None, context, query=query.Query(cls._view))
                d.addCallback(defer.inject_param, 1,
                              query.values, model.connection, item_field)
                return d

            cls.annotate_child_names(fetch_names)

            def fetch_matching(value, context):
                c = query.Condition(item_field, query.Evaluator.equals,
                                    context['key'])
                q = query.Query(cls._view, c)
                d = build_query(None, context, query=q)
                d.addCallback(context['model'].do_select, skip=0)
                d.addCallback(fetch_documents, context)

                def unpack(result):
                    if result:
                        return result[0]

                d.addCallback(unpack)
                return d

            def fetch_source(value, context):
                if cls._query_target == 'source':
                    return fetch_matching(value, context)
                else:
                    return context['model'].source

            cls.annotate_child_source(fetch_source)

            def fetch_view(value, context):
                if cls._query_target == 'view':
                    return fetch_matching(value, context)
                else:
                    return context['view']

            cls.annotate_child_view(fetch_view)


class RangeType(value.Collection):

    value.max_size(2)
    value.min_size(2)
    value.allows(value.Integer())
    value.allows(value.String())

    def validate(self, v):
        v = super(RangeType, self).validate(v)
        return tuple(v)


class FreeList(value.Collection):
    value.allows(value.String())
    value.allows(value.Integer())

    def validate(self, v):
        v = super(FreeList, self).validate(v)
        return tuple(v)


class MetaSortingValue(type(value.Collection)):

    @staticmethod
    def new(name, allowed_fields):
        return value.MetaCollection.new(
            name + 'Field', [SortField(allowed_fields)])


class SortField(value.Collection):

    value.max_size(2)
    value.min_size(2)
    value.allows(value.String())

    def __init__(self, allowed, *args, **kwargs):
        value.Collection.__init__(self, *args, **kwargs)
        self._allowed = allowed

    def validate(self, v):
        v = super(SortField, self).validate(v)
        if v[0] not in self._allowed:
            raise ValueError("Unknown field: '%s'" % (v[0], ))
        try:
            direc = query.Direction[v[1]]
        except KeyError:
            raise ValueError('direction needs to be in %r' %
                             (set(query.Direction)), )
        return (v[0], direc)


class MetaQueryValue(type(value.Collection)):

    @staticmethod
    def new(name, factory, allowed_fields, include_value=list()):
        cls = MetaQueryValue(name, (QueryValue, ),
                             {'factory': factory,
                              'allowed_fields': allowed_fields,
                              'include_value': include_value})
        # this is to make conditions with strings work
        name = name + 'S'
        cls.annotate_allows(
            MetaConditionValue.new(
                name, allowed_fields, ['equals', 'le', 'ge'],
                value.String())())

        # this is to make conditions with numbers work
        name = name + 'I'
        cls.annotate_allows(
            MetaConditionValue.new(
                name, allowed_fields, ['equals', 'le', 'ge'],
                value.Integer())())

        # this is for between evaluator
        name = name + 'R'
        cls.annotate_allows(
            MetaConditionValue.new(
                name, allowed_fields, ['between'], RangeType())())

        # inside operator
        name = name + 'IN'
        cls.annotate_allows(
            MetaConditionValue.new(
                name, allowed_fields, ['inside'], FreeList())())

        cls.annotate_allows(value.Enum(query.Operator))
        return cls


class QueryValue(value.Collection):

    def validate(self, v):
        v = value.Collection.validate(self, v)
        cls = type(self)
        return query.Query(cls.factory, *v, include_value=cls.include_value)

    def publish(self, v):
        return str(v)


class FixedValues(value.Value):

    value.value_type(ValueTypes.string)
    value.options_only()

    implements(IValueOptions)

    def __init__(self, values, *args, **kwargs):
        value.Value.__init__(self, *args, **kwargs)
        for v in values:
            self._add_option(v)


class MetaConditionValue(type(value.Structure)):

    @staticmethod
    def new(name, allowed_fields, evaluators, value_type):
        cls = MetaConditionValue(name, (ConditionValue, ), {})
        cls.annotate_param('field', FixedValues(allowed_fields))
        cls.annotate_param('evaluator', FixedValues(evaluators))
        cls.annotate_param('value', value_type)
        return cls


class ConditionValue(value.Structure):

    def validate(self, v):
        v = value.Structure.validate(self, v)
        return query.Condition(v['field'], query.Evaluator[v['evaluator']],
                               v['value'])

    def publish(self, value):
        return str(value)
