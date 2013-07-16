import operator
import sys
import types

from zope.interface import implements, Interface, Attribute

from feat.common import serialization, enum, first, defer, annotate, log
from feat.database import view

from feat.database.interface import IQueryViewFactory
from feat.database.interface import IPlanBuilder, IQueryCache


class CacheEntry(object):

    def __init__(self, seq_num, entries, keep_value=False):
        self.seq_num = seq_num
        if not keep_value:
            # here entries is just a list of ids
            self.entries = entries
        else:
            # in this case entries is a list of tuples (id, field_value)
            self.entries = list()
            self.values = dict()
            for entry, value in entries:
                self.entries.append(entry)
                self.values[entry] = value

        self.size = sys.getsizeof(entries)


class Cache(log.Logger):

    implements(IQueryCache)

    CACHE_LIMIT = 1024 * 1024 * 20 # 20 MB of memory max

    def __init__(self, logger):
        log.Logger.__init__(self, logger)
        # name -> query -> CacheEntry
        self._cache = dict()

    ### IQueryCache ###

    def empty(self):
        self.log("Emptying query cache.")
        self._cache.clear()

    def query(self, connection, factory, subquery, update_seq=None):
        self.log("query() called for %s view and subquery %r. Update seq: %r",
                 factory.name, subquery, update_seq)
        if update_seq is None:
            d = connection.get_update_seq()
        else:
            d = defer.succeed(update_seq)
        d.addCallback(defer.inject_param, 3,
            self._got_seq_num, connection, factory, subquery)
        return d

    ### public ###

    def get_cache_size(self):
        size = 0
        for name, subcache in self._cache.iteritems():
            for query, entry in subcache.iteritems():
                size += entry.size
        return size

    def on_document_deleted(self, doc_id, rev, deleted, own_change):
        for cache in self._cache.itervalues():
            for entry in cache.itervalues():
                try:
                    entry.entries.remove(doc_id)
                    self.debug("Removed %s from cache results, because it was"
                               " deleted", doc_id)
                except:
                    pass

    ### private, continuations of query process ###

    def _got_seq_num(self, connection, factory, subquery, seq_num):
        if factory.name in self._cache:
            entry = self._cache[factory.name].get(subquery)
            if not entry:
                return self._fetch_subquery(
                    connection, factory, subquery, seq_num)
            elif entry.seq_num == seq_num:
                self.log("Query served from the cache hit, %d rows",
                         len(entry.entries))
                return entry.entries
            else:
                d = connection.get_changes(factory, limit=2,
                                           since=entry.seq_num)
                d.addCallback(defer.inject_param, 4,
                              self._analyze_changes,
                              connection, factory, subquery, entry, seq_num)
                return d
        else:
            return self._fetch_subquery(connection, factory, subquery, seq_num)

    def _fetch_subquery(self, connection, factory, subquery, seq_num):
        controller = factory.get_view_controller(subquery[0])

        keys = controller.generate_keys(*subquery)
        self.log("Will query view %s, with keys %r, as a result of"
                 " subquery: %r", factory.name, keys, subquery)
        d = connection.query_view(factory, parse_results=False, **keys)
        d.addCallback(controller.parse_view_result)
        d.addCallback(self._cache_response, factory, subquery, seq_num,
                      keep_value=controller.keeps_value)
        return d

    def _cache_response(self, entries, factory, subquery, seq_num,
                        keep_value=False):
        self.log("Caching response for %r at seq_num: %d, %d rows",
                 subquery, seq_num, len(entries))
        if factory.name not in self._cache:
            self._cache[factory.name] = dict()
        self._cache[factory.name][subquery] = CacheEntry(seq_num, entries,
                                                         keep_value)
        self._check_size_limit()
        return self._cache[factory.name][subquery].entries

    def _analyze_changes(self, connection, factory, subquery, entry, changes,
                         seq_num):
        if changes['results']:
            self.log("View %s has changed, expiring cache.", factory.name)
            if factory.name in self._cache: # this is not to fail on
                                            # concurrent checks expiring cache
                self._cache[factory.name].clear()
            return self._fetch_subquery(connection, factory, subquery, seq_num)
        else:
            self.log("View %s has not changed, marking cached fragments as "
                     "fresh. %d rows", factory.name, len(entry.entries))
            result = entry.entries
            if factory.name in self._cache:
                for entry in self._cache[factory.name].itervalues():
                    entry.seq_num = seq_num
            return result

    ### private, check that the cache is not too big ###

    def _check_size_limit(self):
        size = self.get_cache_size()
        if size > self.CACHE_LIMIT:
            self._cleanup_old_cache(size - self.CACHE_LIMIT)

    def _cleanup_old_cache(self, to_release):
        entries = [(x.seq_num, x.size, name, subquery)
                   for name, subcache in self._cache.iteritems()
                   for subquery, x in subcache.iteritems()]
        entries.sort(key=operator.itemgetter(0))
        released = 0
        while released < to_release:
            entry = entries.pop(0)
            released += entry[1]
            del self._cache[entry[2]][entry[3]]


class BaseField(object):

    document_types = []

    @staticmethod
    def field_value(doc):
        return iter(list())

    @staticmethod
    def sort_key(value):
        return value

    @staticmethod
    def emit_value(doc):
        return None


class JoinedVersionField(BaseField):

    version_field = None
    target_document_type = None

    @classmethod
    def field_value(cls, doc):
        yield doc.get(cls.version_field)

    @staticmethod
    def sort_key(value):
        import re
        return tuple(int(x) for x in re.findall(r'[0-9]+', value))

    @classmethod
    def emit_value(cls, doc):
        return dict(_id=cls.get_linked_id(doc, cls.target_document_type),
                    value=list(cls.field_value(doc))[0])

    @staticmethod
    def get_linked_id(doc, type_name):
        for row in doc.get('linked', list()):
            if row[0] == type_name:
                return row[1]


class QueryViewMeta(type(view.BaseView)):

    implements(IQueryViewFactory)

    def __init__(cls, name, bases, dct):
        cls.HANDLERS = HANDLERS = dict()
        cls.DOCUMENT_TYPES = DOCUMENT_TYPES = set()
        cls._view_controllers = dict()
        cls._fields = list()

        # map() and filter() function have to be generated separetely for
        # each subclass, because they will have different constants attached
        # in func_globals
        # alrernatively they could be defined inside the subclass of
        # QueryView

        def map(doc):
            if '.type' not in doc or doc['.type'] not in DOCUMENT_TYPES:
                return
            for field, handler in HANDLERS.iteritems():
                if doc['.type'] not in getattr(handler, 'document_types',
                                               DOCUMENT_TYPES):
                    continue

                if hasattr(handler, 'emit_value'):
                    emit_value = handler.emit_value(doc)
                else:
                    emit_value = None

                if hasattr(handler, 'field_value'):
                    values = handler.field_value(doc)
                else:
                    values = handler(doc)
                transform = getattr(handler, 'sort_key', lambda x: x)

                for value in values:
                    yield (field, transform(value)), emit_value
        cls.map = cls._querymethod(dct.pop('map', map))

        def filter(doc, request):
            return doc.get('.type') in DOCUMENT_TYPES
        cls.filter = cls._querymethod(dct.pop('filter', filter))

        # this processes all the annotations
        super(QueryViewMeta, cls).__init__(name, bases, dct)

        cls.attach_dict_of_objects(cls.map, 'HANDLERS')

        cls.DOCUMENT_TYPES.update(set([x for field in HANDLERS.itervalues()
                                       if hasattr(field, 'document_types')
                                       for x in field.document_types]))
        cls.attach_constant(
            cls.map, 'DOCUMENT_TYPES', cls.DOCUMENT_TYPES)
        cls.attach_constant(
            cls.filter, 'DOCUMENT_TYPES', cls.DOCUMENT_TYPES)

    def attach_dict_of_objects(cls, query_method, name):
        # we cannot use normal mechanism for attaching code to query methods,
        # because we want to build a complex object out of it, so we need to
        # inject it after all the annotations have been processed
        names = {}
        obj = getattr(cls, name)
        if not isinstance(obj, dict):
            raise ValueError("%s.%s expected dict, %r found" %
                             (cls, name, obj))
        for field, handler in obj.items():
            if isinstance(handler, types.FunctionType):
                cls.attach_method(query_method, handler)
            elif isinstance(handler, types.TypeType):
                cls.attach_class_definition(query_method, handler)
            else:
                raise ValueError(handler)
            names[field] = handler.__name__
        code = ", ".join(["'%s': %s" % (k, v)
                          for k, v in sorted(names.iteritems())])
        cls.attach_code(query_method, "%s = {%s}" % (name, code))

    def attach_class_definition(cls, query_method, definition):
        mro = definition.mro()
        if mro[1] is not object and mro[1] not in query_method.func_globals:
            cls.attach_class_definition(query_method, mro[1])
        cls.attach_method(query_method, definition)

    ### IQueryViewFactory ###

    @property
    def fields(cls):
        return list(cls._fields)

    def has_field(cls, name):
        return name in cls.HANDLERS

    def get_view_controller(cls, name):
        return cls._view_controllers[name]

    ### annotatations ###

    def _annotate_field(cls, name, handler, controller=None):
        if not hasattr(handler, 'field_value') and not callable(handler):
            raise ValueError(handler)
        cls.HANDLERS[name] = handler
        # the names are kept privately in a list to keep the order of
        # definition
        cls._fields.append(name)
        if controller is None:
            controller = cls.view_controller
        cls._view_controllers[name] = controller(handler, cls)

    def _annotate_document_types(cls, types):
        cls.DOCUMENT_TYPES.update(set(types))


class IQueryViewController(Interface):
    '''
    This is a private interface standarizing the way the QueryCache queries
    the underlying couchdb view and parses its result.
    '''

    keeps_value = Attribute("C{bool} of true parse_view_result() returns 2 "
                            "element tuples with (ID, value). If False "
                            "it returns only IDs")

    def generate_keys(field, evaluator, value):
        '''
        @param field: C{str} name of the field
        @param evaluator: enum values of Evaluator
        @param value: value used
        '''

    def parse_view_result(rows):
        '''
        Transform the rows given by couchdb to a list of IDs.
        The format of those IDs is transparently returned as result of
        select_ids() method.
        '''


class BaseQueryViewController(object):

    implements(IQueryViewController)

    keeps_value = False

    def __init__(self, field, factory=None):
        self._field = field
        self._factory = factory
        if hasattr(self._field, 'sort_key'):
            self.transform = self._field.sort_key
        else:
            self.transform = self._identity

    def generate_keys(self, field, evaluator, value):
        return self._generate_keys(self.transform, field, evaluator, value)

    def parse_view_result(self, rows):
        # the ids are of original documents
        return [x[2] for x in rows]

    ### protected ###

    def _identity(self, value):
        return value

    def _generate_keys(self, transform, field, evaluator, value):
        if evaluator == Evaluator.equals:
            return dict(key=(field, transform(value)))
        if evaluator == Evaluator.le:
            return dict(startkey=(field, ), endkey=(field, transform(value)))
        if evaluator == Evaluator.ge:
            return dict(startkey=(field, transform(value)), endkey=(field, {}))
        if evaluator == Evaluator.between:
            return dict(startkey=(field, transform(value[0])),
                        endkey=(field, transform(value[1])))
        if evaluator == Evaluator.inside:
            return dict(keys=[(field, transform(x)) for x in value])
        if evaluator == Evaluator.none:
            return dict(startkey=(field, ), endkey=(field, {}))


class HighestValueFieldController(BaseQueryViewController):
    '''
    Use this controller to extract the value of a joined field.
    It emits the highest value.
    '''

    # this informs the QueryCache that parse_view_result() will be returning
    # a tuples() including the actual value
    keeps_value = True

    def generate_keys(self, field, evaluator, value):
        s = super(HighestValueFieldController, self).generate_keys
        r = s(field, evaluator, value)
        # we are interesed in the highest value, so here we revert the
        # row order to later only take the highest value
        if 'startkey' in r and 'endkey' in r:
            r['endkey'], r['startkey'] = r['startkey'], r['endkey']
            r['descending'] = True
        return r

    def parse_view_result(self, rows):
        # here we are given multiple values for the same document, we only
        # should take the first one, because we are interested in the highest
        # value
        seen = set()
        result = list()
        for row in rows:
            if row[1]['_id'] not in seen:
                seen.add(row[1]['_id'])
                result.append((row[1]['_id'], row[1]['value']))
        return result


class QueryView(view.BaseView):

    __metaclass__ = QueryViewMeta
    view_controller = BaseQueryViewController


def field(name, definition=None, controller=None):
    if callable(definition):
        annotate.injectClassCallback('query field', 3, '_annotate_field',
                                     name, definition, controller)
    else:
        # used as decorator

        def field(definition):
            annotate.injectClassCallback('query field', 3, '_annotate_field',
                                         name, definition, controller)
            return definition

        return field


def document_types(types):
    annotate.injectClassCallback(
        'document_types', 3, '_annotate_document_types', types)


class Evaluator(enum.Enum):
    '''
    equals: ==
    le: <=
    ge: >=
    between: conjuntion of start_key and end_key
    inside: reflects usage of multiple keys, or python code x in [...]
    none: special value used by sorting operator, fetches the whole index range
    '''

    equals, le, ge, between, inside, none = range(6)


@serialization.register
class Condition(serialization.Serializable):

    implements(IPlanBuilder)

    type_name = 'condition'

    def __init__(self, field, evaluator, value):
        if not isinstance(evaluator, Evaluator):
            raise ValueError("%r is not an Evaluator" % (evaluator, ))

        self.field = field
        self.evaluator = evaluator
        self.value = value

    ### IPlanBuilder ###

    def get_basic_queries(self):
        return [(self.field, self.evaluator, self.value)]

    def __str__(self):
        return "%s %s %s" % (self.field, self.evaluator.name, self.value)


class Operator(enum.Enum):

    AND, OR = range(2)


class Direction(enum.Enum):

    ASC, DESC = range(2)


@serialization.register
class Query(serialization.Serializable):

    implements(IPlanBuilder)

    type_name = 'query'

    def __init__(self, factory, *parts, **kwargs):
        self.factory = IQueryViewFactory(factory)

        self.parts = []
        self.operators = []
        if len(parts) == 0:
            # this is to allow querying with empty query
            field = factory.fields[0]
            parts = [Condition(field, Evaluator.none, None)]

        for index, part in enumerate(parts):
            if index % 2 == 0:
                if not IPlanBuilder.providedBy(part):
                    raise ValueError("Element at index %d should be a Query or"
                                     " condition, %r given" % (index, part))
                for query in part.get_basic_queries():
                    if not factory.has_field(query[0]):
                        raise ValueError("Unknown query field: '%s'" %
                                         (query[0], ))
                self.parts.append(part)

            if index % 2 == 1:
                if not isinstance(part, Operator):
                    raise ValueError("Element at index %d should be an "
                                     "Operator, %r given" % (index, part))
                self.operators.append(part)

        self.include_value = kwargs.pop('include_value', list())

        sorting = kwargs.pop('sorting', None)
        self.set_sorting(sorting)

        if not isinstance(self.include_value, (list, tuple)):
            raise ValueError("%r should be a list or tuple" %
                             (self.include_value), )

        if kwargs:
            raise ValueError('Uknown keywords: %s' % (kwargs.keys(), ))

    def set_sorting(self, sorting):
        self.sorting = sorting
        bad_sorting = ("Sorting should be a list of tuples: (field, direction)"
                       ", %r given" % (self.sorting, ))
        if self.sorting is None:
            # default sorting to by all the fields in ascending order
            self.sorting = [(field, Direction.ASC)
                            for field, _, __ in self.get_basic_queries()]

        if not isinstance(self.sorting, (list, tuple)):
            raise ValueError(bad_sorting)
        for part in self.sorting:
            if not isinstance(part, (list, tuple)) or len(part) != 2:
                raise ValueError(bad_sorting)
            if not isinstance(part[0], (str, unicode)):
                raise ValueError(bad_sorting)
            if not isinstance(part[1], Direction):
                raise ValueError(bad_sorting)

    ### IPlanBuilder ###

    def get_basic_queries(self):
        temp = list()
        for part in self.parts:
            temp.extend(part.get_basic_queries())

        # if we want to sort by the field which is not available in the query
        # we will need to query for the full range of the index
        if self.sorting:
            for sortby, _ in self.sorting:
                included = first(x[0] for x in temp if x[0] == sortby)
                if not included:
                    temp.append((sortby, Evaluator.none, None))

        # if we want a value of some field included in the result we need to
        # make sure its also fetched along the query
        for part in self.include_value:
            included = first(x[0] for x in temp if x[0] == part)
            if not included:
                temp.append((part, Evaluator.none, None))

        # remove duplicates
        resp = list()
        while temp:
            x = temp.pop(0)
            if x not in resp:
                resp.append(x)

        return resp

    def __str__(self):
        ops = [x.name for x in self.operators]
        body = " ".join(str(x) for x in
            filter(None,
                   [x for sublist in map(None, self.parts, ops)
                    for x in sublist]))
        return "(%s)" % (body, )


@defer.inlineCallbacks
def select_ids(connection, query, skip=0, limit=None):
    temp, responses = yield _get_query_response(connection, query)
    if query.sorting:
        temp = sorted(temp, key=_generate_sort_key(responses, query.sorting))
    else:
        temp = list(temp)
    if limit is not None:
        stop = skip + limit
    else:
        stop = None
    r = temp[slice(skip, stop)]
    defer.returnValue(r)


def select(connection, query, skip=0, limit=None):
    d = select_ids(connection, query, skip, limit)
    d.addCallback(connection.bulk_get)
    if query.include_value:
        d.addCallback(include_values, connection.get_query_cache(), query)
    return d


def include_values(docs, cache, query):
    # dict (field, evaluator, value) -> CacheEntry
    cached = cache._cache[query.factory.name]
    # dict field_name -> CacheEntry
    lookup = dict((field, first(v for k, v in cached.iteritems()
                                if k[0] == field))
                  for field in query.include_value)
    for doc in docs:
        for name, cache_entry in lookup.iteritems():
            setattr(doc, name, cache_entry.values.get(doc.doc_id))
    return docs


@defer.inlineCallbacks
def count(connection, query):
    temp, responses = yield _get_query_response(connection, query)
    defer.returnValue(len(temp))


def values(connection, query, field):
    defers = []
    if not query.factory.has_field(field):
        raise ValueError("%r doesn't have %s field defined" %
                         (query.factory, field))
    defers.append(connection.query_view(
        query.factory, startkey=(field, ),
        endkey=(field, {}), parse_results=False))
    defers.append(select_ids(connection, query))
    d = defer.DeferredList(defers)
    d.addCallback(_parse_values_response)
    return d


### private ###


def _parse_values_response(results):
    (s1, rows), (s2, ids) = results
    if not s1:
        return rows
    if not s2:
        return ids

    return set(x[0][1] for x in rows if x[2] in ids)


@defer.inlineCallbacks
def _get_query_response(connection, query):
    cache = connection.get_query_cache()
    responses = dict()
    update_seq = yield connection.get_update_seq()
    for subquery in query.get_basic_queries():
        # subquery -> list of doc ids
        responses[subquery] = yield cache.query(
            connection, query.factory, subquery, update_seq)
    defer.returnValue((_calculate_query_response(responses, query), responses))


def _calculate_query_response(responses, query):
    for_parts = []

    for part in query.parts:
        if isinstance(part, Condition):
            for_parts.append(set(responses[part.get_basic_queries()[0]]))
        elif isinstance(part, Query):
            for_parts.append(_calculate_query_response(responses, part))
    operators = list(query.operators)
    while True:
        if len(for_parts) == 1:
            return for_parts[0]
        oper = operators.pop(0)
        if oper == Operator.AND:
            for_parts[0] = for_parts[0].intersection(for_parts.pop(1))
        elif oper == Operator.OR:
            for_parts[0] = for_parts[0].union(for_parts.pop(1))
        else:
            raise ValueError("Unkown operator '%r' %" (oper, ))


def _generate_sort_key(responses, sorting):

    def sort_key(row):
        positions = list()

        for name, direction in sorting:
            relevant = [v for k, v in responses.iteritems()
                        if k[0] == name]
            for r in relevant:
                try:
                    index = r.index(row)
                    break
                except ValueError:
                    continue
            else:
                index = sys.maxint
            if direction == Direction.DESC:
                index = -index
            positions.append(index)

        return tuple(positions)

    return sort_key
