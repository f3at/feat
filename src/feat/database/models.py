from feat.common import annotate, defer, container, error
from feat.database import query
from feat.models import model, action, value, utils, call, effect
from feat.models import applicationjson
from feat.web import document

from feat.database.interface import IQueryFactory, IDatabaseClient
from feat.models.interface import IContextMaker, ActionCategories
from feat.models.interface import IModel, IValueInfo


def db_connection(effect):
    annotate.injectClassCallback("db_connection", 3, "annotate_db_connection",
                                 effect)


def query_target(target):
    annotate.injectClassCallback("query_target", 3, "annotate_query_target",
                                 target)


def factory(factory, allowed_fields=[],
            item_field=None, include_value=list()):
    annotate.injectClassCallback(
        "factory", 3, "annotate_factory", factory,
        allowed_fields=allowed_fields, include_value=include_value,
        item_field=item_field)


def query_model(model):
    """
    Annotate the effect used to retrieve the model used as a result of the
    query. This is ment to provide the lighter view of the model when its
    retrieved as a list. If this is not specified the child_model is used.

    @param model: the child's model identity, model factory or effect
                  to get it, or None to use IModel adapter.
    @type model: str or unicode or callable or IModelFactory or None
    """
    annotate.injectClassCallback("query_model", 3, "annotate_query_model",
                                 model)


def aggregation(name, value_info, handler, field):
    annotate.injectClassCallback('aggregation', 3, 'annotate_aggregation',
                                 name, value_info, handler, field)


def static_conditions(effect):
    annotate.injectClassCallback('static_conditions', 3,
                                 'annotate_static_conditions',
                                 effect)


def fetch_documents(effect):
    annotate.injectClassCallback('fetch_documents', 3,
                                 'annotate_fetch_documents',
                                 effect)


class QueryViewMeta(type(model.Collection)):
    """
    I'm responsible for post-processing all the annotated attributes of the
    QueryView model and creating the model actions for querying with the
    respect to the parameters and view definition.

    This isn't done in one of the annotations, because if it were, the
    annotations which come afterwards would not be taken into account.
    """

    def __init__(cls, name, bases, dct):
        cls._query_target = None
        cls._query_model = None
        cls._connection_getter = None
        cls._static_conditions = None
        cls._factory = None
        cls._fetch_documents_set = False
        cls._fetch_documents = staticmethod(effect.identity)
        cls._item_field = None

        # this processes all the annotations
        super(QueryViewMeta, cls).__init__(name, bases, dct)

        if cls._factory is None:
            # The class is not annotated with view_factory() annotations
            # This is only valid in the base class, althought no actions
            # should be created.
            return

        # validate that the required annotations have been called
        if cls._query_target is None:
            raise ValueError("This model needs to be annotated with "
                             "query_target(source|view)")

        if not callable(cls._connection_getter):
            raise ValueError("This model needs to be annotated with "
                             "db_connection(effect) annotation")

        # define the Select and Count actions
        name = utils.mk_class_name(cls._factory.name, "Query")
        QueryValue = MetaQueryValue.new(name, cls._factory,
                                        cls._allowed_fields,
                                        cls._include_value)
        result_info = value.Model()

        name = utils.mk_class_name(cls._factory.name, "IncludeValue")
        IncludeValue = value.MetaCollection.new(
            name, [value.FixedValues(cls._allowed_fields)])

        name = utils.mk_class_name(cls._factory.name, "AggregateValue")
        AggregateValue = value.MetaCollection.new(
            name, [value.FixedValues(cls._model_aggregations.keys())])

        build_query = parse_incoming_query(cls._factory,
                                           cls._static_conditions,
                                           cls._include_value,
                                           cls._model_aggregations)

        def render_select_response(value, context, *args, **kwargs):
            cls = type(context['model'])
            if not cls._query_set_factory:
                # query set collection is created only once per class type
                factory = MetaQueryResult.new(cls)
                factory.annotate_meta('json', 'render-as-list')
                cls._query_set_factory = factory
            if cls._fetch_documents_set:
                context['result'].update(value)

            # convert all the aggregate values using their IValueInfo
            if kwargs.get('aggregate'):
                raw_values = context['result'].aggregations
                context['result'].aggregations = dict()
                for index, name in enumerate(kwargs['aggregate']):
                    value_info = cls._model_aggregations[name][0]
                    v = raw_values[index]
                    try:
                        published = value_info.publish(v)
                    except Exception as e:
                        error.handle_exception(
                            None, e, "Failed publishing the result %r", v)
                    else:
                        context['result'].aggregations[name] = published

            result = cls._query_set_factory(context['source'],
                                            context['result'])
            return result.initiate(view=context['view'],
                                   officer=context.get('officer'),
                                   aspect=context.get('aspect'))

        def store_select_result(value, context, *args, **kwargs):
            context['result'], context['responses'] = value
            return value[0]

        def do_include_value(value, context, *args, **kwargs):
            # If there was a custom routing for fetching items defined,
            # we need to call the include_value() explicitely. If
            # query.select() was used, there is no need for that.
            cls = context['model']
            if context['query'].include_value and cls._fetch_documents_set:
                return query.include_values(value, context['responses'],
                                            context['query'])
            else:
                return value

        SelectAction = action.MetaAction.new(
            utils.mk_class_name(cls._factory.name, "Select"),
            ActionCategories.retrieve,
            is_idempotent=False, result_info=result_info,
            effects=(
                build_query,
                call.model_perform('do_select'),
                store_select_result,
                cls._fetch_documents,
                do_include_value,
                render_select_response,
                ),
            params=[action.Param('query', QueryValue()),
                    action.Param('include_value', IncludeValue(),
                                 is_required=False),
                    action.Param('sorting', SortField(cls._allowed_fields),
                                 is_required=False),
                    action.Param('skip', value.Integer(0), is_required=False),
                    action.Param('limit', value.Integer(), is_required=False),
                    action.Param('aggregate', AggregateValue(),
                                 is_required=False),
                    ])
        cls.annotate_action(u"select", SelectAction)

        # define count action
        CountAction = action.MetaAction.new(
            utils.mk_class_name(cls._factory.name, "Count"),
            ActionCategories.retrieve,
            effects=[
                build_query,
                call.model_perform('do_count')],
            result_info=value.Integer(),
            is_idempotent=False,
            params=[action.Param('query', QueryValue())])
        cls.annotate_action(u"count", CountAction)

        # define values action (fetch the values for the range)
        ValuesAction = action.MetaAction.new(
            utils.mk_class_name(cls._factory.name, "Values"),
            ActionCategories.retrieve,
            effects=[
                build_query,
                call.model_perform('fetch_values')],
            # FIXME: the result is a dictionary of name -> [values],
            # consider creating the IValidator for this structure
            result_info=value.Value(),
            is_idempotent=False,
            params=[action.Param('query', QueryValue()),
                    action.Param('fields', IncludeValue())])
        cls.annotate_action(u"values", ValuesAction)

        # define how to fetch items
        if cls._item_field:

            def fetch_names(value, context):
                model = context['model']
                d = build_query(None, context, query=cls._factory())
                d.addCallback(defer.inject_param, 1,
                              query.values, model.connection, cls._item_field)
                return d

            cls.annotate_child_names(fetch_names)

            def fetch_matching(value, context):
                c = query.Condition(
                    cls._item_field, query.Evaluator.equals, context['key'])
                q = cls._factory(c)
                d = build_query(None, context, query=q)
                d.addCallback(context['model'].do_select, skip=0)
                # the result on this points (rows, responses)
                d.addCallback(lambda (r, _): r)
                d.addCallback(cls._fetch_documents, context)

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


def parse_incoming_query(factory, static_conditions=None,
                         include_value=[], model_aggregations=dict()):
    '''
    Effect factory parsing the query value from params and merging in
    the static_conditions specified.

    @param factory: IQueryView
    @param static_conditions: effect to be called to build up static
                               conditions of the query
    @param include_value: list of fields which should be always included
    @param model_aggregations: dict() of name -> (IValueInfo, name, field)
    '''

    def build_query(value, context, *args, **kwargs):

        def merge_conditions(static_conditions, q):
            subquery = factory(*static_conditions)
            return factory(q, query.Operator.AND, subquery, include_value=[])

        def merge_query_options(query, kwargs):
            if kwargs.get('include_value'):
                query.include_value.extend(kwargs['include_value'])
                # reset call below is to get rid of cached query plan
                # if it has been already calculated
                query.reset()
            if kwargs.get('aggregate'):
                aggregate = list()
                for name in kwargs['aggregate']:
                    definition = model_aggregations[name]
                    aggregate.append((definition[1], definition[2]))
                query.aggregate = aggregate
            return query

        def store_in_context(query):
            context['query'] = query
            return query

        if static_conditions:
            d = defer.succeed(None)
            d.addCallback(static_conditions, context)
            d.addCallback(merge_conditions, kwargs['query'])
        else:
            d = defer.succeed(kwargs['query'])
        d.addCallback(merge_query_options, kwargs)
        d.addCallback(store_in_context)
        return d

    return build_query


class QueryView(model.Collection):

    __metaclass__ = QueryViewMeta

    _model_aggregations = container.MroDict('__model_aggregations')

    @classmethod
    def __class__init__(cls, name, bases, dct):
        cls._query_set_factory = None

    def init(self):
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
        return method(self.connection, value, skip, limit,
                      include_responses=True)

    def do_count(self, value):
        return query.count(self.connection, value)

    def fetch_values(self, value, fields):
        res = applicationjson.AsyncDict()
        for field in fields:
            res.add(field, query.values(self.connection, value, field))
        return res.wait()

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
    def annotate_aggregation(cls, name, value_info, handler, field):
        cls._model_aggregations[name] = (IValueInfo(value_info),
                                         handler, field)

    @classmethod
    def annotate_static_conditions(cls, effect):
        cls._static_conditions = model._validate_effect(effect)

    @classmethod
    def annotate_fetch_documents(cls, effect):
        cls._fetch_documents_set = True
        cls._fetch_documents = model._validate_effect(effect)

    @classmethod
    def annotate_factory(cls, factory, allowed_fields=[],
                         include_value=list(),
                         item_field=None):

        cls._factory = IQueryFactory(factory)

        for x in allowed_fields:
            if x not in cls._factory.fields:
                raise ValueError("%r doesn't define a field: '%s'" % (cls, x))
        cls._allowed_fields = allowed_fields

        for x in include_value:
            if x not in cls._factory.fields:
                raise ValueError("%r doesn't define a field: '%s'" % (cls, x))
        cls._include_value = include_value

        if item_field:
            if item_field not in cls._factory.fields:
                raise ValueError("%r doesn't define a field: '%s'" %
                                 (cls, item_field))
            cls._item_field = item_field


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
                             {'factory': IQueryFactory(factory),
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
        return cls.factory(*v, include_value=cls.include_value)

    def publish(self, v):
        return str(v)


class MetaConditionValue(type(value.Structure)):

    @staticmethod
    def new(name, allowed_fields, evaluators, value_type):
        cls = MetaConditionValue(name, (ConditionValue, ), {})
        cls.annotate_param('field', value.FixedValues(allowed_fields))
        cls.annotate_param('evaluator', value.FixedValues(evaluators))
        cls.annotate_param('value', value_type)
        return cls


class ConditionValue(value.Structure):

    def validate(self, v):
        v = value.Structure.validate(self, v)
        return query.Condition(v['field'], query.Evaluator[v['evaluator']],
                               v['value'])

    def publish(self, value):
        return str(value)


class MetaQueryResult(model.MetaCollection):

    @staticmethod
    def new(parent_class):
        # parent_class here is a QueryItemsMixin object
        identity = parent_class._model_identity + '.query'
        cls_name = parent_class.__name__ + "QueryResult"
        target = parent_class._query_target
        cls = MetaQueryResult(cls_name, (QueryResult, ),
                              {"query_target": target})
        cls.annotate_identity(identity)

        if target == 'source':
            cls.annotate_child_source(QueryResult.getter)
            cls.annotate_child_view(parent_class._fetch_view)
        elif target == 'view':
            cls.annotate_child_source(parent_class._fetch_source)
            cls.annotate_child_view(QueryResult.getter)
        else:
            raise AttributeError("Unknown target: %r" % (target, ))
        cls.annotate_child_names(QueryResult.names)
        cls.annotate_child_label(parent_class._item_label)
        cls.annotate_child_desc(parent_class._item_desc)
        cls.annotate_child_model(parent_class._query_model or
                                 parent_class._item_model)
        for meta in parent_class._item_meta:
            cls.annotate_child_meta(*meta)
        for name, meta in parent_class._class_meta.iteritems():
            for value in meta:
                cls.annotate_meta(name, value.value)

        return cls


class QueryResult(model.DynCollection):

    def __init__(self, source, items):
        if not isinstance(items, list):
            raise ValueError(type(items))

        self._items = items
        super(QueryResult, self).__init__(source)

    def get_total_count(self):
        if isinstance(self._items, query.Result):
            return self._items.total_count

    def get_items(self):
        return self._items

    @staticmethod
    def getter(value, context):
        try:
            index = int(context['key'])
            return defer.succeed(context["model"]._items[index])
        except:
            return defer.succeed()

    @staticmethod
    def names(value, context):
        return defer.succeed([str(x)
                              for x in range(len(context["model"]._items))])


def write_query_result(doc, obj, *args, **kwargs):
    # This type of object is used as a result of 'select' query of dbmodels api
    result = list()

    if IModel.implementedBy(obj._item_model):
        model_factory = obj._item_model
    else:
        model_factory = model.get_factory(obj._item_model)
    if model_factory is None:
        # use the adapter
        model_factory = IModel

    items = obj.get_items()
    for child in items:
        if obj.query_target == 'view':
            instance = model_factory(obj.source)
            d = instance.initiate(view=child)
        else:
            instance = model_factory(child)
            d = instance.initiate(view=obj.view)
        d.addCallback(applicationjson.render_inline_model, *args, **kwargs)
        result.append(d)
    r = applicationjson.AsyncDict()
    d = defer.DeferredList(result)
    d.addCallback(applicationjson.unpack_deferred_list_result)
    d.addCallback(list)
    r.add('rows', d)

    r.add('total_count', items.total_count)
    r.add('aggregations', items.aggregations)

    d = r.wait()
    d.addCallback(applicationjson.render_json, doc)
    d.addCallback(defer.override_result, None)
    return d


document.register_writer(write_query_result, applicationjson.MIME_TYPE,
                         QueryResult)


# This used to be defined in this module, prevent all code from
# failing with ImportError
FixedValues = value.FixedValues
