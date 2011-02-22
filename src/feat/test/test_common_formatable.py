from feat.test import common
from feat.common import serialization, formatable


@serialization.register
class Base(formatable.Formatable):

    formatable.field('field1', None)
    formatable.field('field2', 5, 'custom_serializable')


@serialization.register
class Child(Base):

    formatable.field('field1', 'overwritten default')
    formatable.field('field3', None)


class TestFormatable(common.TestCase):

    def setUp(self):
        pass

    def testConstructing(self):
        base = Base(field1=2)
        self.assertEqual(2, base.field1)
        self.assertEqual(5, base.field2)

        self.assertEquals(2, len(base._fields))

        def get_field3(instance):
            return instance.field3

        self.assertRaises(AttributeError, get_field3, base)

    def testOverwritedDefault(self):
        child = Child()
        self.assertEqual('overwritten default', child.field1)

    def testUnknownAttributesInContructor(self):

        def construct():
            i = Base(unknown_field=2)
            return i

        self.assertRaises(AttributeError, construct)

    def testSnapshot(self):
        base = Base(field1=2)
        snapshot = base.snapshot()
        self.assertIsInstance(snapshot, dict)
        self.assertIn('custom_serializable', snapshot)
        self.assertEqual(5, snapshot['custom_serializable'])
        self.assertIn('field1', snapshot)
        self.assertEqual(2, snapshot['field1'])

    def testRecover(self):
        snapshot = dict(field1=5, custom_serializable=4, field3=1)
        instance = Child.__new__(Child)
        instance.recover(snapshot)
        self.assertEqual(5, instance.field1)
        self.assertEqual(4, instance.field2)
        self.assertEqual(1, instance.field3)

    def testNoneValues(self):
        base = Base(field1=0, field2=[])
        self.assertEqual(0, base.field1)
        self.assertEqual([], base.field2)
