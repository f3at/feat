from feat.test import common
from feat.test.integration.common import ModelTestMixin
from feat.common import serialization, defer
from feat.database import models, query, document, emu, view
from feat.models import model, effect, call, getter, value

from feat.models.interface import InvalidParameters


@serialization.register
class QueryDoc(document.Document):
    type_name = 'query'

    document.field('field1', None)
    document.field('field2', None)
    document.field('field3', None)


class QueryView(query.QueryView):

    name = 'query_view'

    def extract_field1(doc):
        yield doc.get('field1')

    def extract_field2(doc):
        yield doc.get('field2')

    def extract_field3(doc):
        yield doc.get('field3')

    query.field('field1', extract_field1)
    query.field('field2', extract_field2)
    query.field('field3', extract_field3)
    query.document_types(['query'])


class DocumentModel(model.Model):
    model.identity('document')
    model.attribute('field1', value.Integer(), getter.source_attr('field1'))
    model.attribute('field2', value.Integer(), getter.source_attr('field2'))
    model.attribute('field3', value.String(), getter.source_attr('field3'))


class QueryModel(models.QueryView):
    model.identity('test')
    model.child_model(DocumentModel)
    models.db_connection(effect.context_value('source'))
    models.view_factory(
        QueryView, ['field1', 'field2'],
        call.model_call('get_static_conditions'))
    model.child_source(getter.model_get('get_doc'))
    models.query_target('source')


    def get_static_conditions(self):
        return [query.Condition('field3', query.Evaluator.equals, 'A')]

    def model_get(self, doc_id):
        return self.connection.get_document(doc_id)


class TestDoingSelectsViaApi(common.TestCase, ModelTestMixin):

    @defer.inlineCallbacks
    def setUp(self):
        self.db = emu.Database()
        self.connection = self.db.get_connection()
        self.model = QueryModel(self.connection)

        views = (QueryView, )
        design_doc = view.DesignDocument.generate_from_views(views)[0]
        yield self.connection.save_document(design_doc)

        for x in range(20):
            if x % 2 == 0:
                field3 = u"A"
            else:
                field3 = u"B"
            yield self.connection.save_document(
                QueryDoc(field1=x, field2=x % 10, field3=field3))

        yield self.model.initiate()

    @defer.inlineCallbacks
    def testQuerySimple(self):
        q = [{'field': 'field1', 'evaluator': 'equals', 'value': 2}]
        res = yield self.model.perform_action('select', query=q)
        yield self._asserts_on_select([2], res)
        count = yield self.model.perform_action('count', query=q)
        self.assertEquals(1, count)

        q = [{'field': 'field1', 'evaluator': 'le', 'value': 10}]
        res = yield self.model.perform_action('select', query=q)
        yield self._asserts_on_select([0, 2, 4, 6, 8, 10], res)
        count = yield self.model.perform_action('count', query=q)
        self.assertEquals(6, count)

        q = [{'field': 'field1', 'evaluator': 'between', 'value': (5, 15)},
             'AND',
             {'field': 'field2', 'evaluator': 'le', 'value': 4}]
        res = yield self.model.perform_action('select', query=q)
        yield self._asserts_on_select([10, 12, 14], res)
        count = yield self.model.perform_action('count', query=q)
        self.assertEquals(3, count)

        res = yield self.model.perform_action('select', query=q,
                                              sorting=[('field1', 'DESC')])
        yield self._asserts_on_select([14, 12, 10], res)

    @defer.inlineCallbacks
    def testPagination(self):
        q = []
        res = yield self.model.perform_action('select', query=q)
        yield self._asserts_on_select([0, 2, 4, 6, 8, 10, 12, 14, 16, 18], res)
        count = yield self.model.perform_action('count', query=q)
        self.assertEquals(10, count)

        res = yield self.model.perform_action('select', query=q, limit=3)
        yield self._asserts_on_select([0, 2, 4], res)
        res = yield self.model.perform_action('select', query=q, limit=3,
                                              skip=3)
        yield self._asserts_on_select([6, 8, 10], res)

        res = yield self.model.perform_action(
            'select', query=q, limit=3, skip=3, sorting=[('field1', 'DESC')])
        yield self._asserts_on_select([12, 10, 8], res)

    @defer.inlineCallbacks
    def testNotAllowedField(self):
        q = [{'field': 'field1', 'evaluator': 'le', 'value': '10'},
             'AND',
             {'field': 'field3', 'evaluator': 'equals', 'value': 'B'}]
        d = self.model.perform_action('select', query=q)
        self.assertFailure(d, InvalidParameters)
        yield d


    @defer.inlineCallbacks
    def _asserts_on_select(self, expected, res):
        items = yield res.fetch_items()
        field1s = []
        for item in items:
            s = yield item.fetch()
            field1 = yield self.modelattr(s, 'field1')
            field1s.append(field1)
        self.assertEqual(expected, field1s)


class TestValues(common.TestCase):

    def testValidateQuery(self):
        QueryValue = models.MetaQueryValue.new(
            'Test', QueryView, ['field1', 'field2'])
        query_value = QueryValue()
        v = query_value.validate([{'field': 'field1', 'evaluator': 'equals',
                                   'value': 'spam'}])
        self.assertIsInstance(v, query.Query)
        self.assertEquals('(field1 equals spam)',
                          query_value.publish(v))


        v = query_value.validate([
            {'field': 'field1', 'evaluator': 'equals', 'value': 'spam'},
            'OR',
            {'field': 'field2', 'evaluator': 'inside', 'value': [1, 2, 3]}])
        self.assertIsInstance(v, query.Query)
        exp = ('(field1 equals spam OR field2 inside [1, 2, 3])')
        self.assertEquals(exp, query_value.publish(v))

        v = query_value.validate([
            {'field': 'field1', 'evaluator': 'equals', 'value': 'spam'},
            'OR',
            {'field': 'field2', 'evaluator': 'between', 'value': [1, 2]}])
        exp = '(field1 equals spam OR field2 between [1, 2])'
        self.assertEquals(exp, query_value.publish(v))

        wrong = [
            {'field': 'field1', 'evaluator': 'equals', 'value': 'spam'},
            {'field': 'field2', 'evaluator': 'between', 'value': [1, 2]}]
        self.assertRaises(ValueError, query_value.validate, wrong)

    def testValidateSorting(self):
        SortingValue = models.MetaSortingValue.new(
            'Test', ['field1', 'field2'])
        sorting = SortingValue()
        v = sorting.validate([['field1', 'DESC']])
        self.assertEquals([('field1', query.Direction.DESC)], v)
        v = sorting.validate([['field1', 'DESC'], ['field2', 'ASC']])
        self.assertEquals([('field1', query.Direction.DESC),
                           ('field2', query.Direction.ASC)], v)
        wrong = [['field1', 'DESC'], ['field2', 'asc']]
        self.assertRaises(ValueError, sorting.validate, wrong)
