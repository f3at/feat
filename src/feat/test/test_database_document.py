from feat.test import common
from feat.common.serialization import json, register
from feat.database import document

import json as sjson


class TestDocument(document.Document):

    type_name = 'test_doc'
    document.field('field', None)


class DocumentSerializationTest(common.TestCase):

    def setUp(self):
        self.serializer = json.Serializer()
        register(TestDocument)
        self.unserializer = json.PaisleyUnserializer()

    def testDocumentWithAttachment(self):
        d = TestDocument(doc_id='some_doc')
        a = d.create_attachment('attachment', 'test attachment', 'text/plain')
        self.assertIsInstance(a, document.Attachment)

        # unsaved attachment should not appear in snapshot
        serialized = self.serialize(d)
        self.assertIn('_attachments', serialized)
        exp = {u'attachment': {u'content_type': u'text/plain',
                               u'follows': True,
                               u'length': 15}}
        self.assertEquals(exp, serialized['_attachments'])

        # once it saved it should be there as a stub
        d.get_attachments()['attachment'].set_saved()
        serialized = self.serialize(d)
        self.assertIn('_attachments', serialized)
        self.assertIn('attachment', serialized['_attachments'])
        self.assertEquals(
            dict(stub=True, length=15, content_type='text/plain'),
            serialized['_attachments']['attachment'])

        # test referencing
        d.field = a
        serialized = self.serialize(d)
        self.assertEquals({'.type': 'attachment', 'name': 'attachment',
                           'doc_id': 'some_doc'},
                          serialized['field'])

    def testLoadingDocumentWithAttachment(self):
        to_load = {'_id': 'some_doc',
                   '.type': 'test_doc',
                   'field': 500,
                   '_attachments': {
                       'attachment': {
                           'stub': True,
                           'length': 40,
                           'content_type': 'text/plain'}}}
        doc = self.unserialize(to_load)
        self.assertIsInstance(doc, TestDocument)
        self.assertEquals('some_doc', doc.doc_id)
        self.assertEquals(500, doc.field)
        self.assertEquals(1, len(doc.attachments))
        self.assertEquals('attachment', doc.attachments.values()[0].name)

        priv = doc.get_attachments()['attachment']
        self.assertTrue(priv.saved)
        self.assertFalse(priv.has_body)
        priv.set_body('Hi world')
        self.assertTrue(priv.saved)
        self.assertTrue(priv.has_body)

    def testUniqieAttachmentNames(self):
        d = TestDocument(doc_id=u'test')
        a = d.create_attachment('attachment', '', unique=True)
        self.assertEqual(a.name, 'attachment')

        a = d.create_attachment('attachment', '', unique=True)
        self.assertEqual(a.name, 'attachment_1')
        a = d.create_attachment('attachment', '', unique=True)
        self.assertEqual(a.name, 'attachment_2')

        a = d.create_attachment('attachment.tar.gz', '', unique=True)
        self.assertEqual(a.name, 'attachment.tar.gz')
        a = d.create_attachment('attachment.tar.gz', '', unique=True)
        self.assertEqual(a.name, 'attachment_1.tar.gz')
        a = d.create_attachment('attachment.tar.gz', '', unique=True)
        self.assertEqual(a.name, 'attachment_2.tar.gz')

        a = d.create_attachment('attachment.json', '', unique=True)
        self.assertEqual(a.name, 'attachment.json')
        a = d.create_attachment('attachment.json', '', unique=True)
        self.assertEqual(a.name, 'attachment_1.json')

    def serialize(self, w):
        return sjson.loads(self.serializer.convert(w))

    def unserialize(self, w):
        return self.unserializer.convert(w)
