from zope.interface import classProvides

from feat.database import query
from feat.database.interface import IViewFactory
from feat.test import common


class DummyView(object):

    classProvides(IViewFactory)

    name = 'dummy'


class DummyQuery(query.Query):

    name = 'dummy'
    query.field(query.Field('field1', DummyView, keeps_value=True))
    query.field(query.Field('field2', DummyView))
    query.field(query.Field('field3', DummyView))


class TestQueryObject(common.TestCase):

    def testValidation(self):
        C = query.Condition
        c1 = C('field1', query.Evaluator.equals, 'value')
        c2 = C('field2', query.Evaluator.equals, 'other')

        # this should be ok
        q = DummyQuery(c1, query.Operator.OR, c2,
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
        q = DummyQuery(c2, sorting=('field1', query.Direction.ASC))
        queries = q.get_basic_queries()
        self.assertIsInstance(queries, list)
        self.assertEqual(2, len(queries))
        self.assertEqual(C('field1', query.Evaluator.none, None),
                         queries[1])
        self.assertEqual(C('field2', query.Evaluator.equals, 'other'),
                         queries[0])

        # empty query should default to something which should give us
        # all the values
        q = DummyQuery()
        queries = q.get_basic_queries()
        self.assertIsInstance(queries, list)
        self.assertEqual(1, len(queries))
        self.assertEqual(C('field1', query.Evaluator.none, None), queries[0])

        # query with aggregations
        q = DummyQuery(aggregate=[['sum', 'field1']])
        self.assertEqual([(DummyQuery.reduce_sum.__func__, 'field1')],
                         q.aggregate)

        # check wrong declarations
        self.assertRaises(ValueError, DummyQuery, c1, c2)
        self.assertRaises(ValueError, DummyQuery, c1,
                          query.Operator.OR, query.Operator.OR)
        self.assertRaises(ValueError, DummyQuery,
                          query.Condition('unknownfield',
                                          query.Evaluator.equals, 1))
        self.assertRaises(ValueError, DummyQuery,
                          aggregation=[['unknown handler', 'field1']])
