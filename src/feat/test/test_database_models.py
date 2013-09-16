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

    @property
    def field4(self):
        return u'value'


class QueryView(query.QueryView):

    name = 'query_view'

    def extract_field1(doc):
        yield doc.get('field1')

    def extract_field2(doc):
        yield doc.get('field2')

    def extract_field3(doc):
        yield doc.get('field3')

    def extract_doc_id(doc):
        yield doc.get('_id')

    query.field('field1', extract_field1)
    query.field('field2', extract_field2)
    query.field('field3', extract_field3)
    query.field('doc_id', extract_doc_id)
    query.document_types(['query'])


class DocumentModel(model.Model):
    model.identity('document')
    model.attribute('field1', value.Integer(), getter.source_attr('field1'))
    model.attribute('field2', value.Integer(), getter.source_attr('field2'))
    model.attribute('field3', value.String(), getter.source_attr('field3'))


class DocumentExtended(DocumentModel):
    model.identity('document-extended')
    model.attribute('field4', value.String(), getter.source_attr('field4'))


class QueryModel(models.QueryView):
    model.identity('test')
    model.child_model(DocumentExtended)
    models.query_model(DocumentModel)
    model.view(effect.static_value('static-view'))
    models.db_connection(effect.context_value('source'))
    models.view_factory(
        QueryView, ['field1', 'field2'],
        call.model_call('get_static_conditions'),
        call.model_filter('fetch_documents'),
        item_field='doc_id')
    models.query_target('source')

    def get_static_conditions(self):
        return [query.Condition('field3', query.Evaluator.equals, 'A')]

    def fetch_documents(self, value):
        self._fetch_documents_called = True
        return self.connection.bulk_get(value)


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
    def testFetchChild(self):
        submodel = yield self.model_descend(self.model, 'query_1')
        self.assertEqual('static-view', submodel.view)
        self.assertIsInstance(submodel, DocumentExtended)
        v = yield self.modelattr(submodel, 'field4')
        self.assertEqual('value', v)

    @defer.inlineCallbacks
    def testFetchItemAsJson(self):
        js = yield self.model_as_json(self.model)
        self.assertIsInstance(js, dict)
        self.assertEqual(10, len(js))
        for k, v in js.iteritems():
            self.assertIsInstance(v, unicode)
            self.assertEqual("root/%s" % (k, ), v)

    @defer.inlineCallbacks
    def testQuerySimple(self):
        q = [{'field': 'field1', 'evaluator': 'equals', 'value': 2}]
        res = yield self.model.perform_action('select', query=q)
        yield self._asserts_on_select([2], res)
        self.assertTrue(self.model._fetch_documents_called)
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
                                              sorting=['field1', 'DESC'])
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
            'select', query=q, limit=3, skip=3, sorting=['field1', 'DESC'])
        yield self._asserts_on_select([12, 10, 8], res)

    @defer.inlineCallbacks
    def testJsonSerialization(self):
        q = []
        res = yield self.model.perform_action('select', query=q)
        j = yield self.model_as_json(res)
        field1s = [0, 2, 4, 6, 8, 10, 12, 14, 16, 18]
        self.assertIsInstance(j, dict)
        self.assertIsInstance(j.get('rows'), list)

        self.assertEqual(len(field1s), len(j['rows']))
        self.assertEqual(len(field1s), j['total_count'])
        for row in j['rows']:
            self.assertIn('field1', row)
            self.assertIn('field2', row)
            self.assertIn('field3', row)
            self.assertEqual(field1s.pop(0), row['field1'])

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
            self.assertIsInstance(s, DocumentModel)
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
        exp = ('(field1 equals spam OR field2 inside (1, 2, 3))')
        self.assertEquals(exp, query_value.publish(v))

        v = query_value.validate([
            {'field': 'field1', 'evaluator': 'equals', 'value': 'spam'},
            'OR',
            {'field': 'field2', 'evaluator': 'between', 'value': [1, 2]}])
        exp = '(field1 equals spam OR field2 between (1, 2))'
        self.assertEquals(exp, query_value.publish(v))

        wrong = [
            {'field': 'field1', 'evaluator': 'equals', 'value': 'spam'},
            {'field': 'field2', 'evaluator': 'between', 'value': [1, 2]}]
        self.assertRaises(ValueError, query_value.validate, wrong)

    def testStringInteger(self):
        QueryValue = models.MetaQueryValue.new(
            'Test', QueryView, ['field1', 'field2'])
        query_value = QueryValue()

        v = query_value.validate([
            {'field': 'field1', 'evaluator': 'equals', 'value': '1234'}])
        self.assertIsInstance(v, query.Query)
        self.assertEquals('1234', v.parts[0].value)

        v = query_value.validate([
            {'field': 'field1', 'evaluator': 'equals', 'value': 1234}])
        self.assertIsInstance(v, query.Query)
        self.assertEquals(1234, v.parts[0].value)

    def testValidateSorting(self):
        sorting = models.SortField(['field1', 'field2'])
        v = sorting.validate(['field1', 'DESC'])
        self.assertEquals(('field1', query.Direction.DESC), v)
        wrong = [['field1', 'DESC']]
        self.assertRaises(ValueError, sorting.validate, wrong)
