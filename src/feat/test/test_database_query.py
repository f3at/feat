from zope.interface import classProvides

from feat.common import defer
from feat.database import query
from feat.test import common


class DummyView(object):
    classProvides(query.IQueryViewFactory)

    fields = ['field1', 'field2', 'field3']

    @classmethod
    def has_field(cls, name):
        return name in cls.fields


class DummyCache(object):

    def __init__(self, stubs):
        self.stubs = stubs

    def query(self, connection, factory, subquery):
        assert isinstance(connection, DummyConnection), repr(connection)
        assert factory is DummyView, repr(factory)
        assert isinstance(subquery, tuple), repr(subquery)
        assert len(subquery) == 3, repr(subquery)

        try:
            return defer.succeed(self.stubs[subquery])
        except KeyError:
            raise AssertionError('%r not in %r' %
                                 (subquery, self.stubs.keys()))


class DummyConnection(object):

    def __init__(self, cache):
        self.cache = cache

    def get_query_cache(self):
        return self.cache

    def get_update_seq(self):
        return defer.succeed(0)

    def bulk_get(self, doc_ids):
        assert isinstance(doc_ids, list), repr(doc_ids)
        return defer.succeed(doc_ids)


class TestWithDummyCache(common.TestCase):

    def setUp(self):
        E = query.Evaluator
        self.cache = DummyCache({
            ('field1', E.equals, 1): ['id1'],
            ('field1', E.equals, 2): ['id2'],
            ('field1', E.equals, 3): ['id3'],
            ('field1', E.equals, 4): ['id4'],
            ('field1', E.none, None): ['id1', 'id2', 'id3', 'id4'],
            ('field1', E.le, 2): ['id1', 'id2'],
            ('field2', E.equals, 'string'): ['id1', 'id3'],
            ('field2', E.equals, 'other'): ['id2', 'id4']})
        self.connection = DummyConnection(self.cache)

    @defer.inlineCallbacks
    def testQuery(self):
        E = query.Evaluator
        C = query.Condition
        O = query.Operator
        D = query.Direction

        yield self._test(['id1'], C('field1', E.equals, 1))
        yield self._test(['id1', 'id2'], C('field1', E.le, 2))
        yield self._test(['id2', 'id1'], C('field1', E.le, 2),
                         sorting=[('field1', D.DESC)])
        yield self._test(['id1', 'id2'], C('field1', E.le, 2),
                         sorting=[('field1', D.ASC)])
        yield self._test(['id2'], C('field1', E.le, 2), O.AND,
                         C('field2', E.equals, 'other'))
        yield self._test(['id1', 'id2', 'id4'], C('field1', E.le, 2), O.OR,
                         C('field2', E.equals, 'other'))
        yield self._test(['id1', 'id2', 'id4', 'id3'],
                         C('field1', E.le, 2), O.OR,
                         C('field2', E.equals, 'other'), O.OR,
                         C('field2', E.equals, 'string'))
        yield self._test(['id1', 'id2', 'id3', 'id4'],
                         C('field2', E.equals, 'other'), O.OR,
                         C('field2', E.equals, 'string'),
                         sorting=[('field1', D.ASC)])
        yield self._test(['id4', 'id3', 'id2', 'id1'],
                         C('field2', E.equals, 'other'), O.OR,
                         C('field2', E.equals, 'string'),
                         sorting=[('field1', D.DESC)])

        subquery = query.Query(DummyView, C('field1', E.equals, 1))
        yield self._test([], C('field1', E.equals, 2), O.AND, subquery)
        yield self._test(['id2', 'id1'], C('field1', E.equals, 2),
                         O.OR, subquery)

    @defer.inlineCallbacks
    def _test(self, result, *parts, **kwargs):
        q = query.Query(DummyView, *parts, sorting=kwargs.pop('sorting', None))
        count = yield query.count(self.connection, q)
        self.assertEquals(len(result), count)
        res = yield query.select(self.connection, q)
        self.assertEquals(result, res)


class TestQueryObject(common.TestCase):

    def testValidation(self):
        c1 = query.Condition('field1', query.Evaluator.equals, 'value')
        c2 = query.Condition('field2', query.Evaluator.equals, 'other')

        # this should be ok
        q = query.Query(
            DummyView, c1, query.Operator.OR, c2,
            sorting=[('field1', query.Direction.ASC)])
        queries = q.get_basic_queries()
        self.assertIsInstance(queries, list)
        self.assertEqual(2, len(queries))
        self.assertEqual(('field1', query.Evaluator.equals, 'value'),
                         queries[0])
        self.assertEqual(('field2', query.Evaluator.equals, 'other'),
                         queries[1])


        #check sorting by not part of the query
        # this should be ok
        q = query.Query(
            DummyView, c2, sorting=[('field1', query.Direction.ASC)])
        queries = q.get_basic_queries()
        self.assertIsInstance(queries, list)
        self.assertEqual(2, len(queries))
        self.assertEqual(('field1', query.Evaluator.none, None),
                         queries[1])
        self.assertEqual(('field2', query.Evaluator.equals, 'other'),
                         queries[0])

        # check wrong declarations
        self.assertRaises(ValueError, query.Query, DummyView)
        self.assertRaises(ValueError, query.Query, DummyView, c1, c2)
        self.assertRaises(ValueError, query.Query, DummyView, c1,
                          query.Operator.OR, query.Operator.OR)
        self.assertRaises(ValueError, query.Query, DummyView,
                          query.Condition('unknownfield',
                                          query.Evaluator.equals, 1))


class QueryView(query.QueryView):
    name = 'dummy'

    query.document_types(['type1', 'type2'])

    def extract_name(doc):
        yield doc.get('name')

    def extract_position(doc):
        pos = doc.get('pos', None)
        if pos is not None:
            yield pos

    query.field('name', extract_name)
    query.field('position', extract_position)


class TestQueryView(common.TestCase):

    def testMap(self):
        code = QueryView.get_code('map')
        self.assertIn("DOCUMENT_TYPES = ['type1', 'type2']", code)
        self.assertIn("HANDLERS = {'position': extract_position, "
                      "'name': extract_name}", code)
        self.assertIn("def extract_position(doc)", code)

        # check that we can get the code multiple times
        code2 = QueryView.get_code('map')
        self.assertEquals(code, code2)

        # now check that map function works (the globals have been injected)
        r = list(QueryView.map({'_id': 'id1', '.type': 'type1',
                                'name': 'John', 'pos': 3}))
        self.assertEqual(2, len(r))
        self.assertIn((('position', 3), 'id1'), r)
        self.assertIn((('name', 'John'), 'id1'), r)

        # name is always emited
        r = list(QueryView.map({'_id': 'id1', '.type': 'type2'}))
        self.assertEqual(1, len(r))
        self.assertIn((('name', None), 'id1'), r)

        # type3 is not supported by this view
        r = list(QueryView.map(
            {'_id': 'id1', '.type': 'type3', 'name': 'John'}))
        self.assertEqual(0, len(r))

    def testFilter(self):
        code = QueryView.get_code('filter')
        self.assertIn("DOCUMENT_TYPES = ['type1', 'type2']", code)

        r = QueryView.filter(
            {'_id': 'id1', '.type': 'type3', 'name': 'John'}, None)
        self.assertIs(False, r)

        r = QueryView.filter(
            {'_id': 'id1', '.type': 'type1', 'name': 'John'}, None)
        self.assertIs(True, r)

