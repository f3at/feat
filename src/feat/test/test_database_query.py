import uuid

from zope.interface import classProvides

from feat.common import defer
from feat.database import query
from feat.test import common


class DummyView(object):
    classProvides(query.IQueryViewFactory)

    name = 'dummy'

    fields = ['field1', 'field2', 'field3']

    reduce_sum = 'dummy'

    aggregations = dict(sum=reduce_sum)

    @classmethod
    def has_field(cls, name):
        return name in cls.fields

    @classmethod
    def get_view_controller(cls, name):
        return (query.BaseViewController
                if name in ('field2', 'field3')
                else query.KeepValueController)


class DummyCache(object):

    def __init__(self, stubs):
        self.stubs = stubs

    def query(self, connection, factory, subquery, seq_num=None):
        assert isinstance(connection, DummyConnection), repr(connection)
        assert factory is DummyView, repr(factory)
        assert isinstance(subquery, query.Condition), repr(subquery)

        try:
            return defer.succeed(query.CacheEntry(0, self.stubs[subquery]))
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
        return defer.succeed(list(doc_ids))


class TestQueryObject(common.TestCase):

    def testValidation(self):
        C = query.Condition
        c1 = C('field1', query.Evaluator.equals, 'value')
        c2 = C('field2', query.Evaluator.equals, 'other')

        # this should be ok
        q = query.Query(
            DummyView, c1, query.Operator.OR, c2,
            sorting=('field1', query.Direction.ASC))
        queries = q.get_basic_queries()
        self.assertIsInstance(queries, list)
        self.assertEqual(2, len(queries))
        self.assertEqual(C('field1', query.Evaluator.equals, 'value'),
                         queries[0])
        self.assertEqual(C('field2', query.Evaluator.equals, 'other'),
                         queries[1])

        #check sorting by not part of the query
        # this should be ok
        q = query.Query(
            DummyView, c2, sorting=('field1', query.Direction.ASC))
        queries = q.get_basic_queries()
        self.assertIsInstance(queries, list)
        self.assertEqual(2, len(queries))
        self.assertEqual(C('field1', query.Evaluator.none, None),
                         queries[1])
        self.assertEqual(C('field2', query.Evaluator.equals, 'other'),
                         queries[0])

        # empty query should default to something which should give us
        # all the values
        q = query.Query(DummyView)
        queries = q.get_basic_queries()
        self.assertIsInstance(queries, list)
        self.assertEqual(1, len(queries))
        self.assertEqual(C('field1', query.Evaluator.none, None), queries[0])

        # query with aggregations
        q = query.Query(DummyView, aggregate=[['sum', 'field1']])
        self.assertEqual([(DummyView.reduce_sum, 'field1')], q.aggregate)

        # check wrong declarations
        self.assertRaises(ValueError, query.Query, DummyView, c1, c2)
        self.assertRaises(ValueError, query.Query, DummyView, c1,
                          query.Operator.OR, query.Operator.OR)
        self.assertRaises(ValueError, query.Query, DummyView,
                          query.Condition('unknownfield',
                                          query.Evaluator.equals, 1))
        self.assertRaises(ValueError, query.Query, DummyView,
                          aggregation=[['unknown handler', 'field1']])


class QueryView(query.QueryView):
    name = 'dummy'

    query.document_types(['type1', 'type2'])

    def extract_name(doc):
        yield doc.get('name')

    query.field('name', extract_name)

    @query.field('position')
    def extract_position(doc):
        pos = doc.get('pos', None)
        if pos is not None:
            yield pos

    BaseField = query.BaseField

    @query.field('complex')
    class ComplexField(BaseField):

        document_types = ['type1']

        @staticmethod
        def field_value(doc):
            yield doc.get('pos')

        @staticmethod
        def sort_key(value):
            return 20 - value

        @staticmethod
        def emit_value(doc):
            return doc.get('name')

    @query.field('another_complex')
    class AnotherComplexField(BaseField):

        document_types = []


class TestQueryView(common.TestCase):

    def testMap(self):
        code = QueryView.get_code('map')
        self.assertIn("DOCUMENT_TYPES = set(['type1', 'type2'])", code)
        self.assertIn("HANDLERS = {'another_complex': AnotherComplexField, "
                      "'complex': ComplexField, "
                      "'name': extract_name, "
                      "'position': extract_position}", code)
        self.assertIn("def extract_position(doc)", code)
        self.assertIn("class ComplexField(BaseField)", code)
        self.assertIn("    @staticmethod\n    def field_value(doc):", code)
        self.assertEqual(1, code.count("class BaseField(object)"))

        # decorators need to be cleared out
        self.assertNotIn("@query.field", code)

        # check that we can get the code multiple times
        code2 = QueryView.get_code('map')
        self.assertEquals(code, code2)

        # now check that map function works (the globals have been injected)
        r = list(QueryView.map({'_id': 'id1', '.type': 'type1',
                                'name': 'John', 'pos': 3}))
        self.assertEqual(3, len(r))
        self.assertIn((('position', 3), None), r)
        self.assertIn((('name', 'John'), None), r)
        self.assertIn((('complex', 17), 'John'), r) # 17 = 20 - 3

        # name is always emited
        r = list(QueryView.map({'_id': 'id1', '.type': 'type2'}))
        self.assertEqual(1, len(r))
        self.assertIn((('name', None), None), r)

        # type3 is not supported by this view
        r = list(QueryView.map(
            {'_id': 'id1', '.type': 'type3', 'name': 'John'}))
        self.assertEqual(0, len(r))

