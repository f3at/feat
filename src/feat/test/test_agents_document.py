# -*- Mode: Python -*-
# vi:si:et:sw=4:sts=4:ts=4

import json

from feat.agents import document

from . import common


class TestDocument(common.TestCase):

    def testIsSerializable(self):
        doc = document.Document(_id=111)
        serialized = doc.to_json()

        unserialized = json.loads(serialized)
        self.assertEqual(111, unserialized['_id'])

    def testSubclassIncludesSuperclassFields(self):

        class Child(document.Document):

            fields = ['field1', 'field2']

        doc = Child(field1='abcd')
        self.assertTrue('_id' in doc._fields)
        self.assertTrue('_rev' in doc._fields)

        serialized = doc.to_json()

        unserialized = json.loads(serialized)
        self.assertEqual('abcd', unserialized['field1'])

    def testRaisesOnUnknownKey(self):
        self.assertRaises(AttributeError, document.Document, unknown_key='aaa')
