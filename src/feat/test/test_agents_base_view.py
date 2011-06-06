from feat.test import common
from feat.agents.base import view
from feat.common import text_helper


class SomeView(view.BaseView):

    name = 'some_view'

    def map(doc):
        yield doc['_id'], doc['_id']


class ReducingView(view.BaseView):

    name = 'reducing_view'
    use_reduce = True

    def map(doc):
        yield doc['_id'], 1

    def reduce(keys, values):
        return len(values)


class TestDesignDocument(common.TestCase):

    def testGenerateDesignDoc(self):
        views = (SomeView, ReducingView, )
        doc = view.DesignDocument.generate_from_views(views)

        self.assertIsInstance(doc, view.DesignDocument)
        self.assertEquals(u'python', doc.language)
        self.assertEquals(2, len(doc.views))
        self.assertIn('some_view', doc.views)
        self.assertIn('map', doc.views['some_view'])
        expected = "def map(doc):\n    yield doc['_id'], doc['_id']"
        self.assertEqual(expected, doc.views['some_view']['map'])
        self.assertNotIn('reduce', doc.views['some_view'])

        self.assertIn('reducing_view', doc.views)
        self.assertIn('map', doc.views['reducing_view'])
        self.assertIn('reduce', doc.views['reducing_view'])
