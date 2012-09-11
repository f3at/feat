from zope.interface import classProvides

from feat.common import defer
from feat.database import query
from feat.test import common


class DummyView(object):
    classProvides(query.IQueryViewFactory)

    fields = ['field1', 'field2', 'field3']


class DummyCache(object):

    def __init__(self, stubs):
        self.stubs = stubs

    def query(self, connection, factory, subquery, update_seq):
        assert isinstance(connection, DummyConnection), repr(connection)
        assert factory is DummyView, repr(factory)
        assert isinstance(subquery, tuple), repr(subquery)
        assert len(subquery) == 3, repr(subquery)
        assert update_seq == 0, repr(update_seq)

        try:
            return defer.succeed(self.stubs[subquery])
        except KeyError:
            raise AssertionError('%r not in %r' % (subquery, self.stubs.keys()))


class DummyConnection(object):

    def __init__(self, cache):
        self.cache = cache

    def get_query_cache(self):
        return self.cache

    def info(self):
        return defer.succeed(dict(update_seq=0))

    def bulk_get(self, doc_ids):
        assert isinstance(doc_ids, list), repr(doc_ids)
        return defer.succeed(doc_ids)


class TestWithDummyCache(common.TestCase):

    def setUp(self):
        E = query.Evaluator
        C = query.Condition
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
        Q = query.Query
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
