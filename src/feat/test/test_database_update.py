
from feat.database import update, document
from feat.test import common

from feat.database.interface import ResignFromModifying


class DummyDoc(document.Document):

    document.field('field1', None)
    document.field('field2', None)


class TestUpdateAttributes(common.TestCase):

    def setUp(self):
        self.doc = DummyDoc(field1=5, field2=dict(a=0, b=1, c=2))

    def testUpdateAttribute(self):
        doc = update.attributes(self.doc, dict(field1=10, field2=50))
        self.assertEqual(10, doc.field1)
        self.assertEqual(50, doc.field2)

    def testMispelledNames(self):
        self.assertRaises(AttributeError, update.attributes, self.doc,
                          dict(misspelled=2, field1=200))

    def testUpdateInDict(self):
        doc = update.attributes(self.doc, {'field1': 10,
                                           ('field2', 'a'): 50,
                                           ('field2', 'd'): 8})
        self.assertEqual(10, doc.field1)
        self.assertEqual(dict(a=50, b=1, c=2, d=8), doc.field2)

    def testUpdateInNestedObject(self):
        doc = update.attributes(self.doc, {'field1': DummyDoc()})
        self.assertIsInstance(doc.field1, DummyDoc)

        doc = update.attributes(self.doc, {('field1', 'field1'): 50})
        self.assertIsInstance(doc.field1, DummyDoc)
        self.assertEqual(50, doc.field1.field1)

        # now it raises exception
        self.assertRaises(AttributeError,
                          update.attributes, self.doc,
                          {('field1', 'mispelled'): 50})
        self.assertRaises(KeyError,
                          update.attributes, self.doc,
                          {('field2', 'mispelled', 'a'): 50})

    def testResign(self):
        self.assertRaises(ResignFromModifying, update.attributes, self.doc,
                          {'field1': 5})
        self.assertRaises(ResignFromModifying, update.attributes, self.doc,
                          {('field2', 'a'): 0})
