from zope.interface import implements

from feat.common import annotate, defer
from feat.database import query
from feat.models import model, action, value, utils, call

from feat.database.interface import IQueryViewFactory, IDatabaseClient
from feat.models.interface import IContextMaker, ActionCategories
from feat.models.interface import IValueOptions, ValueTypes


def db_connection(effect):
    annotate.injectClassCallback("db_connection", 3, "annotate_db_connection",
                                 effect)


def view_factory(factory, allowed_fields=[], static_conditions=[]):
    annotate.injectClassCallback(
        "view_factory", 3, "annotate_view_factory",
        factory, allowed_fields=[], static_conditions=[])


class QueryView(model.Collection):

    model.child_meta('json', 'render-inline')

    def init(self):
        if not callable(type(self)._connection_getter):
            raise ValueError("This model needs to be annotated with "
                             "db_connection(effect) annotation")
        if type(self)._view is None:
            raise ValueError("This model needs to be annotated with "
                             "view_factory(IQueryViewFactory)")

        context = IContextMaker(self).make_context()
        d = self._connection_getter(None, context)
        d.addCallback(self._set_connection)
        return d

    ### private ###

    def _set_connection(self, connection):
        self.connection = IDatabaseClient(connection)

    ### action body implementation ###

    def get_static_conditions(value, context):

        def build_query(static_conditions, q):
            subquery = query.Query(cls.factory, *static_conditions)
            return query.Query(cls.factory, q, query.Operator.AND, subquery)

        cls = type(context['model'])
        if cls._static_conditions:
            d = cls._static_conditions(None, context)
            d.addCallback(build_query, value)
            return d
        return defer.succeed(value)

    def do_select(self, query, skip, sorting=None, limit=None):
        if sorting:
            query.set_sorting(sorting)
        return query.select(self.connection, query, skip, limit)

    def render_select_response(self, value):
        if not hasattr(self, '_query_set_factory'):
            factory = model.MetaQuerySetCollection.new(type(self))
            self._query_set_factory = factory
        result = self._query_set_factory(self.source, value)
        return result.initiate(view=self.view, officer=self.officer,
                               aspect=self.aspect)

    def do_count(self, query):
        return query.count(self.connection, query)

    ### annotations ###

    @classmethod
    def annotate_db_connection(cls, effect):
        cls._connection_getter = model._validate_effect(effect)

    @classmethod
    def annotate_view_factory(cls, factory, allowed_fields=[],
                              static_conditions=None):
        cls._view = IQueryViewFactory(factory)
        cls._static_conditions = (static_conditions and
                                  model._validate_effect(static_conditions))

        for x in allowed_fields:
            if not cls.view.has_field(x):
                raise ValueError("%r doesn't define a field: '%s'" % (x, ))
        cls._allowed_fields = allowed_fields

        # define query action
        name = utils.mk_class_name(cls._view.name, "Query")
        QueryValue = MetaQueryValue.new(name, cls._view, cls._allowed_fields)
        name = utils.mk_class_name(cls._view.name, "Sorting")
        SortingValue = MetaSortingValue.new(name, cls._allowed_fields)
        name = utils.mk_class_name(cls._view.name, "Result")
        result_info = value.MetaCollection.new(name, [value.Model()])()

        SelectAction = action.MetaAction.new(
            utils.mk_class_name(cls._view.name, "Select"),
            ActionCategories.retrieve,
            is_idempotent=False, result_info=result_info,
            effects=[call.model_perform('do_select')],
            params=[action.Param('query', QueryValue()),
                    action.Param('sorting', SortingValue(), is_required=False),
                    action.Param('skip', value.Integer(0), is_required=False),
                    action.Param('limit', value.Integer(), is_required=False)])
        cls.annotate_action(u"select", SelectAction)

        # define count action
        CountAction = action.MetaAction.new(
            utils.mk_class_name(cls._view.name, "Count"),
            ActionCategories.retrieve,
            effects=[call.model_perform('do_count')],
            result_info=value.Integer(),
            params=[action.Param('query', QueryValue())])
        cls.annotate_action(u"count", CountAction)


class RangeType(value.Collection):

    value.max_size(2)
    value.min_size(2)
    value.allows(value.Integer())


class FreeList(value.Collection):
    value.allows(value.Integer())
    value.allows(value.String())


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
    def new(name, factory, allowed_fields):
        cls = MetaQueryValue(name, (QueryValue, ), {'factory': factory})
        # this is to make conditions with numbers work
        name = name + 'I'
        cls.annotate_allows(
            MetaConditionValue.new(
                name, allowed_fields, ['equals', 'le', 'ge'],
                value.Integer())())

        # this is to make conditions with strings work
        name = name + 'S'
        cls.annotate_allows(
            MetaConditionValue.new(
                name, allowed_fields, ['equals', 'le', 'ge'],
                value.String())())

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
        q = query.Query(cls.factory, *v)
        return q

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
