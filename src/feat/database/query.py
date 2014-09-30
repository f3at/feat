import decimal
import inspect
import time

from zope.interface import implements, classProvides

from feat.common import serialization, enum, first, defer, annotate, error
from feat.common import container

from feat.database.interface import IPlanBuilder, IQueryField, IQueryFactory
from feat.database.interface import IQueryIndex
from feat.interface.serialization import IRestorator, ISerializable


class ParsedIndex(object):

    implements(IQueryIndex)

    def __init__(self, entries, keep_value=False):
        self.includes_values = keep_value
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

    def get_value(self, id):
        return self.values.get(id)


class Field(object):

    implements(IQueryField)

    keeps_value = False

    def __init__(self, field, view, id_key='_id', index_field=None,
                 **kwargs):
        self.field = field
        self.index_field = index_field or field
        self.view = view
        self.keeps_value = kwargs.pop('keeps_value', type(self).keeps_value)
        self.id_key = id_key
        if 'sorting' in kwargs:
            self.transform = kwargs.pop('sorting')
        else:
            self.transform = identity
        if kwargs:
            raise TypeError('Uknown parameters: %s' %
                            (", ".join(kwargs.keys())))

    ### IQueryField ###

    def fetch(self, connection, condition, if_modified_since=None):
        assert isinstance(condition, Condition), repr(type(condition))

        keys = self.generate_keys(condition.evaluator, condition.value)
        cache_id_suffix = "#%s/%s" % (self.view.name, id(self))
        return connection.query_view(self.view, parse_results=False,
                                     cache_id_suffix=cache_id_suffix,
                                     post_process=self.parse_view_result,
                                     if_modified_since=if_modified_since,
                                     **keys)

    ### protected ###

    def generate_keys(self, evaluator, value):
        return generate_keys(self.transform, self.index_field, evaluator,
            value)

    def parse_view_result(self, rows, tag):
        # If the row emitted the link with _id=doc_id this value is used,
        # otherwise the id of the emiting document is used
        if self.keeps_value:
            parsed = [(x[1].get(self.id_key, x[2]), x[1].get('value', x[0][1]))
                      if isinstance(x[1], dict)
                      else (x[2], x[0][1]) for x in rows]
        else:
            parsed = [x[1][self.id_key]
                      if isinstance(x[1], dict) and self.id_key in x[1]
                      else x[2] for x in rows]
        return ParsedIndex(parsed, keep_value=self.keeps_value)

    ### python ###

    def __str__(self):
        return "<Field: %s/%s>" % (self.view.name, self.field)


identity = lambda x: x


class HighestValueField(Field):
    '''
    Use this controller to extract the value of a joined field.
    It emits the highest value.
    '''

    # this informs the QueryCache that parse_view_result() will be returning
    # a tuples() including the actual value
    keeps_value = True

    def generate_keys(self, evaluator, value):
        s = super(HighestValueField, self).generate_keys
        r = s(evaluator, value)
        # we are interesed in the highest value, so here we revert the
        # row order to later only take the highest value
        if 'startkey' in r and 'endkey' in r:
            r['endkey'], r['startkey'] = r['startkey'], r['endkey']
            r['descending'] = True
        return r

    def parse_view_result(self, rows, tag):
        # here we are given multiple values for the same document, we only
        # should take the first one, because we are interested in the highest
        # value
        seen = set()
        result = list()
        for row in rows:
            if row[1][self.id_key] not in seen:
                seen.add(row[1][self.id_key])
                result.append((row[1][self.id_key], row[1]['value']))
        return ParsedIndex(result, keep_value=True)


class ListValueField(Field):

    keeps_value = True

    def parse_view_result(self, rows, tag):
        # here we are given multiple values for the same document,
        # we compile them to lists of values so that the view index like:
        # ['preapproved_by', 'lender1'], {'_id': 'merchant_record_1'}
        # ['preapproved_by', 'lender2'], {'_id': 'merchant_record_1'}
        # ['preapproved_by', 'lender3'], {'_id': 'merchant_record_1'}
        # ['preapproved_by', 'lender1'], {'_id': 'merchant_record_2'}
        # ...
        # is resolved to the following:
        # [('merchant_record_1', ['lender1', 'lender2', 'lender3']),
        #  ('merchant_record_2', ['lender1'])]
        indexes = dict() # doc_id -> index in result table
        result = list()
        for row in rows:
            doc_id = (row[1][self.id_key]
                      if (row[1] and self.id_key in row[1]) else row[2])
            if doc_id not in indexes:
                indexes[doc_id] = len(result)
                result.append((doc_id, list()))
            result[indexes[doc_id]][1].append(row[0][1])
        return ParsedIndex(result, keep_value=True)


class SumValueField(Field):

    keeps_value = True

    def parse_view_result(self, rows, tag):
        # here we are given multiple float values for the same document,
        # we parse them as decimals and sum

        # ['loan_amount', 1002.2], {'_id': 'merchant_record_1'}
        # ['loan_amount', 2001.2], {'_id': 'merchant_record_2'}
        # ...
        # is resolved to the following:
        # [('merchant_record_1', decimal.Decimal('1002.20')),
        #  ('merchant_record_2', decimal.Decimal('2001.20'))]

        indexes = dict() # doc_id -> index in result table
        result = list()
        for row in rows:
            if row[1] and self.id_key in row[1]:
                doc_id = row[1][self.id_key]
            else:
                doc_id = row[2]
            if doc_id not in indexes:
                indexes[doc_id] = len(result)
                result.append((doc_id, decimal.Decimal()))
            try:
                v = decimal.Decimal(str(row[0][1]))
            except:
                error.handle_exception(None, None,
                                       'Failed parsing decimal value')
                continue
            else:
                result[indexes[doc_id]] = (
                    doc_id, result[indexes[doc_id]][1] + v)

        return ParsedIndex(result, keep_value=True)


def generate_keys(transform, field, evaluator, value):
    '''
    Generates the query keys for the default structure of the query index.
    The structure of the key: [field_name, value].
    It supports custom sorting, in which case the value is substituted
    bu the result of transform(value).

    @param transform: callable of 1 argument
    @param field: C{str} field name
    @param evaluator: C{Evaluator}
    @param value: value
    @rtype: dict
    @returns: keys to use to query the view
    '''

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


def field(handler):
    annotate.injectClassCallback('query field', 3, '_annotate_field', handler)


def aggregation(name):

    def aggregation(handler):
        annotate.injectClassCallback('aggregate', 3, '_annotate_aggregation',
                                     name, handler)
        return handler

    return aggregation


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
        if isinstance(value, list):
            value = tuple(value)
        self.value = value

    ### IPlanBuilder ###

    def get_basic_queries(self):
        return [self]

    ### end of IPlanBuilder ###

    def __str__(self):
        return "%s %s %s" % (self.field, self.evaluator.name, self.value)

    def __repr__(self):
        return '<Condition: "%s">' % (self, )

    def __hash__(self):
        return hash((self.field, self.evaluator, self.value))

    def __eq__(self, other):
        if not isinstance(other, Condition):
            return NotImplemented
        return (self.field == other.field and
                self.evaluator == other.evaluator and
                self.value == other.value)

    def __ne__(self, other):
        if not isinstance(other, Condition):
            return NotImplemented
        return not self.__eq__(other)


class Operator(enum.Enum):

    AND, OR = range(2)


class Direction(enum.Enum):

    ASC, DESC = range(2)


class QueryMeta(type(serialization.Serializable), annotate.MetaAnnotable):

    implements(IQueryFactory)

    def __init__(cls, name, bases, dct):
        cls.aggregations = container.MroDict("__mro__aggregations__")
        cls.fields = container.MroDict("__mro__fields__")
        cls.default_field = None

        if 'name' not in dct:
            cls.name = cls.__name__

        super(QueryMeta, cls).__init__(name, bases, dct)

    ### anotation hooks ###

    def _annotate_field(cls, field):
        if not cls.fields:
            cls.default_field = field.field

        cls.fields[field.field] = field

    def _annotate_aggregation(cls, name, handler):
        if not callable(handler):
            raise ValueError(handler)
        spec = inspect.getargspec(handler)
        if len(spec.args) != 1:
            raise ValueError("%r should take a single parameter, values" %
                             (handler, ))
        cls.aggregations[name] = handler


@serialization.register
class Query(serialization.Serializable):

    __metaclass__ = QueryMeta
    implements(IPlanBuilder)

    type_name = 'query'

    def __init__(self, *parts, **kwargs):
        self.parts = []
        self.operators = []
        if len(parts) == 0:
            # This is to allow querying with empty query. The default field
            # is the first one defined for this class.
            parts = [Condition(self.default_field, Evaluator.none, None)]

        for index, part in enumerate(parts):
            if index % 2 == 0:
                if not IPlanBuilder.providedBy(part):
                    raise ValueError("Element at index %d should be a Query or"
                                     " condition, %r given" % (index, part))
                for query in part.get_basic_queries():
                    if query.field not in self.fields:
                        raise ValueError("Unknown query field: '%s'" %
                                         (query.field, ))
                self.parts.append(part)

            if index % 2 == 1:
                if not isinstance(part, Operator):
                    raise ValueError("Element at index %d should be an "
                                     "Operator, %r given" % (index, part))
                if self.operators and part not in self.operators:
                    raise ValueError("Sorry, mixing different operators inside"
                                     "a query is not currently supported. "
                                     "Please use nested queries instead")
                self.operators.append(part)

        self.include_value = list(kwargs.pop('include_value', list()))

        if not isinstance(self.include_value, (list, tuple)):
            raise ValueError("%r should be a list or tuple" %
                             (self.include_value), )

        self.aggregate = kwargs.pop('aggregate', None)

        sorting = kwargs.pop('sorting', None)
        self.set_sorting(sorting)

        if kwargs:
            raise ValueError('Unknown keywords: %s' % (kwargs.keys(), ))

    def _get_aggregate(self):
        if hasattr(self, '_processed_aggregate'):
            return self._processed_aggregate

    def _set_aggregate(self, aggregate):
        self._processed_aggregate = list()
        self.reset()
        if aggregate is not None:
            msg = ('aggregate param should be a list of tuples of'
                   ' the form (handler, field), passed: %r')

            if not isinstance(aggregate, list):
                raise ValueError(msg % (aggregate, ))
            for entry in aggregate:
                if not (isinstance(entry, (list, tuple)) and
                        len(entry) == 2):
                    raise ValueError(msg % (entry, ))
                handler, field = entry
                if not handler in self.aggregations:
                    raise ValueError("Unknown aggregate handler: %r" %
                                     (handler, ))
                if not field in self.fields:
                    raise ValueError("Unknown aggregate field: %r" % (field, ))
                controller = self.fields[field]
                if not controller.keeps_value:
                    raise ValueError("The controller used for the field: %s "
                                     "is not marked as the one which keeps "
                                     "the value. Aggregation cannot work"
                                     " for such index." % (field, ))

                self._processed_aggregate.append(
                    (self.aggregations[handler], field))

    aggregate = property(_get_aggregate, _set_aggregate)

    def set_sorting(self, sorting):
        self.reset()
        self.sorting = sorting
        bad_sorting = ("Sorting should be a tuple: (field, direction)"
                       ", %r given" % (self.sorting, ))

        if self.sorting is None:
            # default sorting to the first field of the query, ascending order
            field = self.get_basic_queries()[0].field
            self.sorting = (field, Direction.ASC)

        if not isinstance(self.sorting, (list, tuple)):
            raise ValueError(bad_sorting)
        if len(self.sorting) != 2:
            raise ValueError(bad_sorting)
        if not isinstance(self.sorting[0], (str, unicode)):
            raise ValueError(bad_sorting)
        if not isinstance(self.sorting[1], Direction):
            raise ValueError(bad_sorting)

    def reset(self):
        try:
            del self._cached_basic_queries
        except AttributeError:
            pass

    ### IPlanBuilder ###

    def get_basic_queries(self):
        if not hasattr(self, '_cached_basic_queries'):
            temp = list()
            for part in self.parts:
                temp.extend(part.get_basic_queries())

            # if we want to sort by the field which is not available in
            # the query we will need to query for the full range of the
            # index
            if self.sorting:
                sortby = self.sorting[0]
                if not first(x for x in temp if sortby == x.field):
                    temp.append(Condition(sortby, Evaluator.none, None))

            # if we want a value of some field included in the result we
            # need to make sure its also fetched along the query
            for part in self.include_value + [x[1] for x in self.aggregate]:
                included = first(x.field for x in temp if x.field == part)
                if not included:
                    temp.append(Condition(part, Evaluator.none, None))


            # remove duplicates
            self._cached_basic_queries = resp = list()
            while temp:
                x = temp.pop(0)
                if x not in resp:
                    resp.append(x)

        return self._cached_basic_queries

    ### shared aggregations ###

    @aggregation('sum')
    def reduce_sum(values):
        l = list(values)
        return sum(l)

    ### python ###

    def __str__(self):
        ops = [x.name for x in self.operators]
        body = " ".join(str(x) for x in
            filter(None,
                   [x for sublist in map(None, self.parts, ops)
                    for x in sublist]))
        return "(%s)" % (body, )


@serialization.register
class Result(list):

    type_name = 'feat.database.query.Result'

    classProvides(IRestorator)
    implements(ISerializable)

    total_count = None
    aggregations = None

    def update(self, new_list):
        del self[:]
        self.extend(new_list)

    ### ISerializable ###

    def snapshot(self):
        r = {'rows': list(self)}
        if self.total_count:
            r['total_count'] = self.total_count
        if self.aggregations:
            r['aggregations'] = self.aggregations
        return r

    def recover(self, snapshot):
        self.update(snapshot['rows'])
        if 'total_count' in snapshot:
            self.total_count = snapshot['total_count']
        if 'aggregations' in snapshot:
            self.aggregations = snapshot['aggregations']

    ### IRestorator ###

    @classmethod
    def prepare(cls):
        return cls()


@defer.inlineCallbacks
def select_ids(connection, query, skip=0, limit=None,
               include_responses=False):
    temp, responses = yield _get_query_response(connection, query)

    total_count = len(temp)
    if limit is not None:
        stop = skip + limit
    else:
        stop = None

    name, direction = query.sorting
    index = first(v.entries
                  for k, v in responses.iteritems() if k.field == name)

    if direction == Direction.DESC:
        index = reversed(index)

    if query.aggregate:
        # we have to copy the collection, because _get_sorted_slice()
        # treats it as a buffer, and modifies the content
        aggregate_index = set(temp)

    r = Result(_get_sorted_slice(index, temp, skip, stop))
    r.total_count = total_count

    # count reductions for aggregated fields based on the view index
    if query.aggregate:
        r.aggregations = list()
        for handler, field in query.aggregate:
            value_index = first(v for k, v in responses.iteritems()
                                if k.field == field)
            r.aggregations.append(handler(
                x for x in value_iterator(aggregate_index, value_index)))
    if include_responses:
        defer.returnValue((r, responses))
    else:
        defer.returnValue(r)


def value_iterator(index, value_index):
    for x in index:
        v = value_index.get_value(x)
        if v is not None:
            yield v


@defer.inlineCallbacks
def select(connection, query, skip=0, limit=None, include_responses=False):
    res, responses = yield select_ids(connection, query, skip, limit,
                                      include_responses=True)
    temp = yield connection.bulk_get(res)
    res.update(temp)

    if query.include_value:
        yield include_values(res, responses, query)
    if include_responses:
        defer.returnValue((res, responses))
    else:
        defer.returnValue(res)


def include_values(docs, responses, query):
    # dict field_name -> ParsedIndex
    lookup = dict((field, first(v for k, v in responses.iteritems()
                                if k.field == field))
                  for field in query.include_value)
    for doc in docs:
        for name, cache_entry in lookup.iteritems():
            setattr(doc, name, cache_entry.get_value(doc.doc_id))
    return docs


@defer.inlineCallbacks
def count(connection, query):
    temp, responses = yield _get_query_response(connection, query)
    defer.returnValue(len(temp))


@defer.inlineCallbacks
def values(connection, query, field, unique=True):
    if field not in query.fields:
        raise ValueError("%r doesn't have %s field defined" %
                         (type(query), field))
    query.include_value.append(field)
    query.reset() # ensures the field condition gets included

    temp, responses = yield _get_query_response(connection, query)
    index = first(v for k, v in responses.iteritems()
                  if k.field == field)
    if not index.includes_values:
        raise ValueError('The query controller of %s field '
                         'of %s query is not marked to '
                         'keep the value in the cache. You have to enable '
                         'it to make query.value() work.' %
                         (field, query.name))
    if unique:
        resp = set()
        for x in temp:
            resp.add(index.get_value(x))
        defer.returnValue(list(resp))
    else:
        resp = list()
        for x in temp:
            resp.append(index.get_value(x))
        defer.returnValue(resp)


### private ###


def _do_fetch(connection, responses, ctime, factory, subquery):
    d = factory.fields[subquery.field].fetch(
        connection, subquery, if_modified_since=ctime)
    d.addCallback(defer.inject_param, 1, responses.__setitem__,
                  subquery)
    d.addErrback(_fail_on_subquery, connection, subquery)
    return d


@defer.inlineCallbacks
def _get_query_response(connection, query):
    responses = dict()
    defers = list()

    # First query should be performed separetely so that we know its ETag.
    # This allows not making additional requests when they are not needed.
    ctime = time.time()
    subqueries = query.get_basic_queries()

    if subqueries:
        subquery = subqueries[0]
        yield _do_fetch(connection, responses, ctime, query, subquery)

        for subquery in subqueries[1:]:
            defers.append(_do_fetch(
                connection, responses, ctime, query, subquery))

    if defers:
        r = yield defer.DeferredList(defers, consumeErrors=True)
        for success, res in r:
            if not success:
                defer.returnValue(res)

    defer.returnValue((_calculate_query_response(responses, query), responses))


def _fail_on_subquery(fail, connection, subquery):
    error.handle_failure(connection, fail,
                         "Failed querying subquery %s", subquery)
    return fail


def _calculate_query_response(responses, query):
    for_parts = []

    for part in query.parts:
        if isinstance(part, Condition):
            key = part.get_basic_queries()[0]
            for_parts.append(set(responses[key].entries))
        elif isinstance(part, Query):
            for_parts.append(_calculate_query_response(responses, part))
    if len(for_parts) == 1:
        return for_parts[0]

    operators = list(query.operators)
    if operators[0] == Operator.AND:
        return set.intersection(*for_parts)
    elif operators[0] == Operator.OR:
        return set.union(*for_parts)
    else:
        raise ValueError("Unkown operator '%r' %" (operators[0], ))


def _get_sorted_slice(index, rows, skip, stop):
    seen = 0
    if stop is None:
        stop = len(rows)

    for value in index:
        if not rows:
            return
        try:
            rows.remove(value)
        except KeyError:
            continue

        seen += 1
        if skip < seen <= stop:
            yield value
        if seen > stop:
            break
    else:
        # if we haven't reached the sorted target,
        # now just return the rows as they appear
        missing = stop - seen
        try:
            for x in range(missing):
                yield rows.pop()
        except KeyError:
            pass
