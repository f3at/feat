import operator
import sys

from zope.interface import implements

from feat.common import serialization, enum, first, defer, annotate, log
from feat.database import view

from feat.database.interface import IQueryViewFactory
from feat.database.interface import IPlanBuilder, IQueryCache


class CacheEntry(object):

    def __init__(self, seq_num, entries):
        self.seq_num = seq_num
        self.entries = entries
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
        self.debug("Emptying query cache.")
        self._cache.clear()

    def query(self, connection, factory, subquery):
        self.debug("query() called for %s view and subquery %r", factory.name,
                   subquery)
        d = connection.get_update_seq()
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

    ### private, continuations of query process ###

    def _got_seq_num(self, connection, factory, subquery, seq_num):
        if factory.name in self._cache:
            entry = self._cache[factory.name].get(subquery)
            if not entry:
                return self._fetch_subquery(
                    connection, factory, subquery, seq_num)
            elif entry.seq_num == seq_num:
                self.debug("Query served from the cache hit, %d rows",
                           len(entry.entries))
                return entry.entries
            else:
                d = connection.get_changes(factory, limit=1,
                                           since=entry.seq_num)
                d.addCallback(defer.inject_param, 4,
                              self._analyze_changes,
                              connection, factory, subquery, entry, seq_num)
                return d
        else:
            return self._fetch_subquery(connection, factory, subquery, seq_num)

    def _fetch_subquery(self, connection, factory, subquery, seq_num):
        keys = self._generate_keys(*subquery)
        self.log("Will query view %s, with keys %r, as a result of"
                 " subquery: %r", factory.name, keys, subquery)
        d = connection.query_view(factory, **keys)
        d.addCallback(defer.keep_param,
                      self._cache_response, factory, subquery, seq_num)
        return d

    def _cache_response(self, entries, factory, subquery, seq_num):
        self.debug("Caching response for %r at seq_num: %d, %d rows",
                   subquery, seq_num, len(entries))
        if factory.name not in self._cache:
            self._cache[factory.name] = dict()
        self._cache[factory.name][subquery] = CacheEntry(seq_num, entries)
        self._check_size_limit()

    def _analyze_changes(self, connection, factory, subquery, entry, changes,
                         seq_num):
        if changes['results']:
            self.debug("View %s has changed, expiring cache.", factory.name)
            if factory.name in self._cache: # this is not to fail on
                                            # concurrent checks expiring cache
                self._cache[factory.name].clear()
            d = self._fetch_subquery(connection, factory, subquery, seq_num)
            d.addCallback(defer.keep_param,
                          self._cache_response, factory, subquery, seq_num)
            return d
        else:
            self.debug("View %s has not changed, marking cached fragments as "
                       "fresh. %d rows", factory.name, len(entry.entries))
            result = entry.entries
            if factory.name in self._cache:
                for entry in self._cache[factory.name].itervalues():
                    entry.seq_num = seq_num
            return result

    def _generate_keys(self, field, evaluator, value):
        if evaluator == Evaluator.equals:
            return dict(key=(field, value))
        if evaluator == Evaluator.le:
            return dict(startkey=(field, ), endkey=(field, value))
        if evaluator == Evaluator.ge:
            return dict(startkey=(field, value), endkey=(field, {}))
        if evaluator == Evaluator.between:
            return dict(startkey=(field, value[0]), endkey=(field, value[1]))
        if evaluator == Evaluator.inside:
            return dict(keys=[(field, x) for x in value])
        if evaluator == Evaluator.none:
            return dict(startkey=(field, ), endkey=(field, {}))

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


class QueryViewMeta(type(view.BaseView)):

    implements(IQueryViewFactory)

    def __init__(cls, name, bases, dct):
        cls.HANDLERS = HANDLERS = dict()
        cls.DOCUMENT_TYPES = DOCUMENT_TYPES = list()

        # map() and filter() function have to be generated separetely for
        # each subclass, because they will have different constants attached
        # in func_globals
        # alrernatively they could be defined inside the subclass of
        # QueryView

        def map(doc):
            if doc['.type'] not in DOCUMENT_TYPES:
                return
            for field, handler in HANDLERS.iteritems():
                for value in handler(doc):
                    yield (field, value), None
        cls.map = cls._querymethod(dct.pop('map', map))

        def filter(doc, request):
            return doc.get('.type') in DOCUMENT_TYPES
        cls.filter = cls._querymethod(dct.pop('filter', filter))

        # this processes all the annotations
        super(QueryViewMeta, cls).__init__(name, bases, dct)

        # we cannot use normal mechanism for attaching code to query methods,
        # because we want to build a complex object out of it, so we need to
        # inject it after all the annotations have been processed
        names = {}
        for field, handler in cls.HANDLERS.iteritems():
            cls.attach_method(cls.map, handler)
            names[field] = handler.__name__
        code = ", ".join(["'%s': %s" % (k, v)
                          for k, v in names.iteritems()])
        cls.attach_code(cls.map, "HANDLERS = {%s}" % code)
        cls.attach_constant(
            cls.map, 'DOCUMENT_TYPES', cls.DOCUMENT_TYPES)
        cls.attach_constant(
            cls.filter, 'DOCUMENT_TYPES', cls.DOCUMENT_TYPES)


class QueryView(view.BaseView):

    __metaclass__ = QueryViewMeta

    ### IViewFactory ###

    @classmethod
    def parse_view_result(cls, rows, reduced, include_docs):
        return [x[2] for x in rows]

    ### IQueryViewFactory ###

    @classmethod
    def has_field(cls, name):
        return name in cls.HANDLERS

    ### annotatations ###

    @classmethod
    def _annotate_field(cls, name, handler):
        cls.HANDLERS[name] = handler

    @classmethod
    def _annotate_document_types(cls, types):
        cls.DOCUMENT_TYPES.extend(types)


def field(name, extract=None):
    if callable(extract):
        annotate.injectClassCallback('query field', 3, '_annotate_field',
                                     name, extract)
    else:
        # used as decorator

        def field(extract):
            annotate.injectClassCallback('query field', 3, '_annotate_field',
                                         name, extract)
            return extract

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
            raise ValueError("Empty query?")

        for part, index in zip(parts, range(len(parts))):
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

        sorting = kwargs.pop('sorting', None)
        self.set_sorting(sorting)

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
    defer.returnValue(temp[slice(skip, stop)])


def select(connection, query, skip=0, limit=None):
    d = select_ids(connection, query, skip, limit)
    d.addCallback(connection.bulk_get)
    return d


@defer.inlineCallbacks
def count(connection, query):
    temp, responses = yield _get_query_response(connection, query)
    defer.returnValue(len(temp))


### private ###


@defer.inlineCallbacks
def _get_query_response(connection, query):
    cache = connection.get_query_cache()
    responses = dict()
    for subquery in query.get_basic_queries():
        # subquery -> list of doc ids
        responses[subquery] = yield cache.query(
            connection, query.factory, subquery)
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
