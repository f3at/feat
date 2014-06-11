# F3AT - Flumotion Asynchronous Autonomous Agent Toolkit
# Copyright (C) 2010,2011 Flumotion Services, S.A.
# All rights reserved.

# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License along
# with this program; if not, write to the Free Software Foundation, Inc.,
# 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA.

# See "LICENSE.GPL" in the source distribution for more information.

# Headers in this file shall remain intact.

from feat.common import enum
from feat.models import interface, value

from feat.test import common

from feat.models.interface import UnknownParameters, InvalidParameters
from feat.models.interface import MissingParameters


class DummyString(value.String):
    value.label("Dummy")
    value.desc("Dummy test string")
    value.default("spam")


class DummyStringOptions(value.String):
    value.label(u"StrOpt")
    value.desc(u"String with options")
    value.option(u"egg", is_default=False)
    value.option("bacon", True, "Bacon")
    value.option("spam", False, u"Spamn spam and spam")
    value.option(u"beans", label="Some beans")


class DummyStringMoreOptions(DummyStringOptions):
    value.desc("String with more options")
    value.option(u"foo", is_default=True)
    value.options_only()


class DummyStringEvenMoreOptions(DummyStringMoreOptions):
    value.option(u"bar")


class DummyEnum(enum.Enum):

    toto, tata, titi = range(3)
    popo = enum.value(42, "Other Value")


class TestCollection1(value.Collection):
    value.allows(value.Integer())


class TestCollection2(value.Collection):
    value.allows(value.String())
    value.allows(value.Boolean())
    value.min_size(2)
    value.max_size(4)


class TestStructure(value.Structure):
    value.field("field1", value.Integer(), is_required=True)
    value.field("string", value.String(), is_required=False)
    value.field("field2", value.Integer(6), is_required=False)


class DictObject(object):

    def __init__(self, **params):
        self._params = params

    def __getattr__(self, name):
        if name not in self._params:
            raise AttributeError(name)
        return self._params[name]


class TestModelsValue(common.TestCase):

    def testStructure(self):
        v = TestStructure()

        res = v.validate(dict(field1=2, string="hi", field2=10))
        self.assertEqual(2, res['field1'])
        self.assertEqual('hi', res['string'])
        self.assertEqual(10, res['field2'])

        res = v.validate(dict(field1=2))
        self.assertEqual(2, res['field1'])
        self.assertNotIn('string', res)
        self.assertEqual(6, res['field2'])

        self.assertRaises(InvalidParameters, v.validate,
                          dict(field1='string'))
        self.assertRaises(MissingParameters, v.validate,
                          dict(field2=10))
        self.assertRaises(UnknownParameters, v.validate,
                          dict(field1=1, unknown=10))

        res = v.publish(dict(field1=1, string='12'))
        self.assertEqual(dict(field1=1, string='12', field2=6), res)
        res = v.publish(DictObject(field1=1, string='12'))
        self.assertEqual(dict(field1=1, string='12', field2=6), res)
        # missing required field
        self.assertRaises(ValueError, v.publish, dict(string=1))
        self.assertRaises(ValueError, v.publish, DictObject(string=1))

    def testCollection(self):
        v = TestCollection1()
        self.assertTrue(interface.IValueInfo.providedBy(v))
        self.assertTrue(interface.IValueCollection.providedBy(v))
        self.assertEqual(v.value_type, interface.ValueTypes.collection)
        self.assertFalse(v.use_default)

        self.assertEqual(v.publish([]), [])
        self.assertEqual(v.publish([1]), [1])
        self.assertEqual(v.publish([1, 2, 3]), [1, 2, 3])
        self.assertRaises(ValueError, v.publish, 45)
        self.assertRaises(ValueError, v.publish, "spam")
        self.assertRaises(ValueError, v.publish, ["spam"])
        self.assertRaises(ValueError, v.publish, [25, "42"])
        self.assertRaises(ValueError, v.publish, [[1, 2]])

        self.assertEqual(v.validate([]), [])
        self.assertEqual(v.validate([1]), [1])
        self.assertEqual(v.validate([1, 2, 3]), [1, 2, 3])
        self.assertEqual(v.validate([25, "42"]), [25, 42])
        self.assertRaises(ValueError, v.validate, 45)
        self.assertRaises(ValueError, v.validate, "spam")
        self.assertRaises(ValueError, v.validate, ["spam"])
        self.assertRaises(ValueError, v.validate, [[1, 2]])

        v = TestCollection2()
        self.assertTrue(interface.IValueInfo.providedBy(v))
        self.assertTrue(interface.IValueCollection.providedBy(v))
        self.assertEqual(v.value_type, interface.ValueTypes.collection)
        self.assertFalse(v.use_default)

        self.assertRaises(ValueError, v.publish, [])
        self.assertRaises(ValueError, v.publish, ["spam"])
        self.assertRaises(ValueError, v.publish, [True])
        self.assertEqual(v.publish(["spam", "bacon"]), ["spam", "bacon"])
        self.assertEqual(v.publish(["spam", "bacon", "sausage"]),
                         ["spam", "bacon", "sausage"])
        self.assertEqual(v.publish([True, False]), [True, False])
        self.assertEqual(v.publish([True, False, True]), [True, False, True])
        self.assertEqual(v.publish(["spam", True]), ["spam", True])
        self.assertEqual(v.publish([True, "bacon", False, "sausage"]),
                         [True, "bacon", False, "sausage"])
        self.assertRaises(ValueError, v.publish, [1])
        self.assertRaises(ValueError, v.publish, [1, 2])
        self.assertRaises(ValueError, v.publish, [1, 2, 3])
        self.assertRaises(ValueError, v.publish, [25, "42"])
        self.assertRaises(ValueError, v.publish, [[True, False]])
        self.assertRaises(ValueError, v.publish,
                          [True, True, True, True, True])
        self.assertRaises(ValueError, v.publish,
                          ["a", "b", "c", "d", "e"])
        self.assertRaises(ValueError, v.publish,
                          ["a", True, "c", False, "e"])

        self.assertRaises(ValueError, v.validate, [])
        self.assertRaises(ValueError, v.validate, ["spam"])
        self.assertRaises(ValueError, v.validate, [True])
        self.assertEqual(v.validate(["spam", "bacon"]), ["spam", "bacon"])
        self.assertEqual(v.validate(["spam", "bacon", "sausage"]),
                         ["spam", "bacon", "sausage"])
        self.assertEqual(v.validate([True, False]), [True, False])
        self.assertEqual(v.validate([True, False, True]), [True, False, True])
        self.assertEqual(v.validate(["spam", True]), ["spam", True])
        self.assertEqual(v.validate([True, "bacon", False, "sausage"]),
                         [True, "bacon", False, "sausage"])
        self.assertRaises(ValueError, v.validate, [1])
        self.assertRaises(ValueError, v.validate, [1, 2])
        self.assertRaises(ValueError, v.validate, [1, 2, 3])
        self.assertRaises(ValueError, v.validate, [25, "42"])
        self.assertRaises(ValueError, v.validate, [[True, False]])
        self.assertRaises(ValueError, v.validate,
                          [True, True, True, True, True])
        self.assertRaises(ValueError, v.validate,
                          ["a", "b", "c", "d", "e"])
        self.assertRaises(ValueError, v.validate,
                          ["a", True, "c", False, "e"])

    def testBaseValue(self):
        s = value.Value()
        self.assertTrue(interface.IValueInfo.providedBy(s))
        self.assertEqual(s.label, None)
        self.assertEqual(s.desc, None)
        self.assertEqual(s.value_type, None)
        self.assertFalse(s.use_default)
        self.assertEqual(s.validate(""), "")
        self.assertEqual(s.validate(8), 8)
        self.assertEqual(s.validate(None), None)
        self.assertEqual(s.publish(None), None)
        self.assertEqual(s.publish("test"), "test")
        self.assertEqual(s.publish(42), 42)
        self.assertFalse(s.has_option("spam"))
        self.assertEqual(s.get_option("spam"), None)
        self.assertEqual(s.count_options(), 0)
        self.assertEqual(list(s.iter_options()), [])

    def testStringValue(self):
        v = value.String()
        self.assertTrue(interface.IValueInfo.providedBy(v))
        self.assertFalse(interface.IValueOptions.providedBy(v))
        self.assertEqual(v.value_type, interface.ValueTypes.string)
        self.assertFalse(v.use_default)

        self.assertEqual(v.validate(""), u"")
        self.assertEqual(v.validate("spam"), u"spam")
        self.assertEqual(v.validate(u"bacon"), u"bacon")
        self.assertTrue(isinstance(v.validate("egg"), unicode))
        self.assertTrue(isinstance(v.validate(u"egg"), unicode))
        self.assertRaises(ValueError, v.validate, None)
        self.assertRaises(ValueError, v.validate, 42)

        self.assertEqual(v.publish(u"test"), u"test")
        self.assertEqual(v.publish("not unicode"), u"not unicode")
        self.assertTrue(isinstance(v.publish("egg"), unicode))
        self.assertRaises(ValueError, v.publish, 42)
        self.assertRaises(ValueError, v.publish, None)

        self.assertEqual(v.as_string(u"test"), u"test")
        self.assertEqual(v.as_string("not unicode"), u"not unicode")
        self.assertTrue(isinstance(v.as_string("egg"), unicode))
        self.assertRaises(ValueError, v.as_string, 42)
        self.assertRaises(ValueError, v.as_string, None)

        v = value.String(default="FOO")
        self.assertTrue(v.use_default)
        self.assertEqual(v.default, u"FOO")
        self.assertTrue(isinstance(v.default, unicode))

        self.assertEqual(v.validate(None), u"FOO")
        self.assertTrue(isinstance(v.validate(None), unicode))
        self.assertEqual(v.publish(None), u"FOO")
        self.assertTrue(isinstance(v.publish(None), unicode))

        v = value.String("FOO")
        self.assertTrue(v.use_default)
        self.assertEqual(v.default, u"FOO")
        self.assertTrue(isinstance(v.default, unicode))

        self.assertEqual(v.validate(None), u"FOO")
        self.assertEqual(v.publish(None), u"FOO")

        self.assertRaises(ValueError, value.String, "foo", "bar")
        self.assertRaises(ValueError, value.String, "foo", default="bar")
        self.assertRaises(ValueError, value.String, spam="bar")

        v = DummyString()
        self.assertTrue(interface.IValueInfo.providedBy(v))
        self.assertFalse(interface.IValueOptions.providedBy(v))
        self.assertEqual(v.label, u"Dummy")
        self.assertTrue(isinstance(v.label, unicode))
        self.assertEqual(v.desc, u"Dummy test string")
        self.assertTrue(isinstance(v.desc, unicode))
        self.assertEqual(v.value_type, interface.ValueTypes.string)
        self.assertTrue(v.use_default)
        self.assertEqual(v.default, u"spam")
        self.assertTrue(isinstance(v.default, unicode))

        self.assertEqual(v.validate(None), u"spam")
        self.assertTrue(isinstance(v.validate(None), unicode))

        self.assertEqual(v.publish(None), u"spam")
        self.assertTrue(isinstance(v.publish(None), unicode))
        self.assertRaises(ValueError, v.publish, 42)

        v = DummyString(default=u"bacon")
        self.assertTrue(v.use_default)
        self.assertEqual(v.default, u"bacon")
        self.assertTrue(isinstance(v.default, unicode))
        self.assertEqual(v.validate(None), u"bacon")
        self.assertTrue(isinstance(v.validate(None), unicode))

        v = DummyStringOptions()
        self.assertTrue(interface.IValueInfo.providedBy(v))
        self.assertTrue(interface.IValueOptions.providedBy(v))
        self.assertEqual(v.label, u"StrOpt")
        self.assertTrue(isinstance(v.label, unicode))
        self.assertEqual(v.desc, u"String with options")
        self.assertTrue(isinstance(v.desc, unicode))
        self.assertEqual(v.value_type, interface.ValueTypes.string)
        self.assertTrue(v.use_default)
        self.assertEqual(v.default, u"bacon")
        self.assertTrue(isinstance(v.default, unicode))

        self.assertEqual(v.validate(""), u"")
        self.assertEqual(v.validate("toto"), u"toto")
        self.assertTrue(isinstance(v.validate("toto"), unicode))
        self.assertEqual(v.validate(None), u"bacon")
        self.assertTrue(isinstance(v.validate(None), unicode))

        self.assertEqual(v.publish(u"egg"), u"egg")
        self.assertTrue(isinstance(v.validate(u"egg"), unicode))
        self.assertEqual(v.publish("spam"), u"spam")
        self.assertTrue(isinstance(v.validate("spam"), unicode))
        self.assertEqual(v.publish(u"spam"), u"spam")
        self.assertEqual(v.publish(u"toto"), u"toto")

        self.assertEqual(v.count_options(), 4)
        self.assertTrue(v.has_option("egg"))
        self.assertTrue(v.has_option("spam"))
        self.assertFalse(v.has_option("foo"))
        self.assertTrue(v.has_option(u"egg"))
        self.assertTrue(v.has_option(u"spam"))
        self.assertFalse(v.has_option(u"foo"))
        self.assertEqual(v.get_option("beans").value, u"beans")
        self.assertEqual(v.get_option("beans").label, u"Some beans")
        self.assertTrue(isinstance(v.get_option("beans").value, unicode))
        self.assertEqual(v.get_option(u"bacon").value, u"bacon")
        self.assertEqual(v.get_option(u"bacon").label, u"Bacon")
        self.assertTrue(isinstance(v.get_option(u"bacon").value, str))
        self.assertEqual(v.get_option("foo"), None)
        self.assertEqual([o.value for o in v.iter_options()],
                         [u"egg", u"bacon", u"spam", u"beans"])
        self.assertEqual([o.label for o in v.iter_options()],
                         [u"egg", u"Bacon", u"Spamn spam and spam",
                          u"Some beans"])

        v = DummyStringMoreOptions()
        self.assertTrue(interface.IValueInfo.providedBy(v))
        self.assertTrue(interface.IValueOptions.providedBy(v))
        self.assertEqual(v.label, "StrOpt")
        self.assertEqual(v.desc, "String with more options")
        self.assertTrue(v.use_default)
        self.assertEqual(v.default, u"foo")

        self.assertEqual(v.validate(None), u"foo")
        self.assertRaises(ValueError, v.validate, "toto")

        self.assertEqual(v.publish(u"foo"), u"foo")
        self.assertEqual(v.publish(u"spam"), u"spam")
        self.assertRaises(ValueError, v.publish, u"toto")

        self.assertEqual(v.count_options(), 5)
        self.assertTrue(v.has_option("egg"))
        self.assertTrue(v.has_option("spam"))
        self.assertTrue(v.has_option("foo"))
        self.assertFalse(v.has_option("bar"))
        self.assertEqual([o.value for o in v.iter_options()],
                         [u"egg", u"bacon", u"spam", u"beans", u"foo"])
        self.assertEqual([o.label for o in v.iter_options()],
                         [u"egg", u"Bacon", u"Spamn spam and spam",
                          u"Some beans", u"foo"])

        v = DummyStringEvenMoreOptions()
        self.assertTrue(v.has_option("bar"))

    def testIntegerValue(self):
        v = value.Integer()
        self.assertTrue(interface.IValueInfo.providedBy(v))
        self.assertFalse(interface.IValueOptions.providedBy(v))
        self.assertEqual(v.value_type, interface.ValueTypes.integer)
        self.assertFalse(v.use_default)

        self.assertEqual(v.validate(0), 0)
        self.assertEqual(v.validate(-456), -456)
        self.assertEqual(v.validate(12345678901234567890),
                         12345678901234567890)
        self.assertEqual(v.validate(-12345678901234567890),
                         -12345678901234567890)
        self.assertEqual(v.validate("0"), 0)
        self.assertEqual(v.validate("-456"), -456)
        self.assertEqual(v.validate("12345678901234567890"),
                         12345678901234567890)
        self.assertEqual(v.validate("-12345678901234567890"),
                         -12345678901234567890)
        self.assertEqual(v.validate(u"0"), 0)
        self.assertEqual(v.validate(u"-456"), -456)
        self.assertEqual(v.validate(u"12345678901234567890"),
                         12345678901234567890)
        self.assertEqual(v.validate(u"-12345678901234567890"),
                         -12345678901234567890)
        self.assertRaises(ValueError, v.validate, None)
        self.assertRaises(ValueError, v.validate, "spam")

        self.assertEqual(v.publish(0), 0)
        self.assertEqual(v.publish(42), 42)
        self.assertEqual(v.publish(-33), -33)
        self.assertEqual(v.publish(12345678901234567890),
                         12345678901234567890)
        self.assertEqual(v.publish(-12345678901234567890),
                         -12345678901234567890)
        self.assertRaises(ValueError, v.publish, "42")
        self.assertEqual(v.publish(3.14), 3)

        self.assertEqual(v.as_string(0), u"0")
        self.assertTrue(isinstance(v.as_string(0), unicode))
        self.assertEqual(v.as_string(42), "42")
        self.assertEqual(v.as_string(-33), "-33")
        self.assertEqual(v.as_string(12345678901234567890),
                         "12345678901234567890")
        self.assertEqual(v.as_string(-12345678901234567890),
                         "-12345678901234567890")
        self.assertRaises(ValueError, v.as_string, "42")

        v = value.Integer(default=88)
        self.assertTrue(v.use_default)
        self.assertEqual(v.default, 88)
        self.assertTrue(isinstance(v.default, int))
        self.assertEqual(v.validate(None), 88)

        self.assertEqual(v.validate(None), 88)
        self.assertEqual(v.publish(None), 88)
        self.assertEqual(v.as_string(None), "88")

        v = value.Integer(44)
        self.assertTrue(v.use_default)
        self.assertEqual(v.default, 44)
        self.assertTrue(isinstance(v.default, int))
        self.assertEqual(v.validate(None), 44)

        self.assertEqual(v.validate(None), 44)
        self.assertEqual(v.publish(None), 44)
        self.assertEqual(v.as_string(None), "44")

    def testEnumValue(self):
        v = value.Enum(DummyEnum)
        self.assertTrue(interface.IValueInfo.providedBy(v))
        self.assertTrue(interface.IValueOptions.providedBy(v))
        self.assertEqual(v.value_type, interface.ValueTypes.string)
        self.assertFalse(v.use_default)

        self.assertEqual([o.value for o in v.iter_options()],
                         [u"toto", u"tata", u"titi", u"Other Value"])
        self.assertTrue(all(isinstance(o.value, unicode)
                            for o in v.iter_options()))
        self.assertEqual([o.label for o in v.iter_options()],
                         [u"toto", u"tata", u"titi", u"Other Value"])
        self.assertTrue(all(isinstance(o.label, unicode)
                            for o in v.iter_options()))

        self.assertEqual(v.validate(0), DummyEnum.toto)
        self.assertTrue(isinstance(v.validate(0), DummyEnum))
        self.assertEqual(v.validate(42), DummyEnum.popo)
        self.assertTrue(isinstance(v.validate(42), DummyEnum))
        self.assertEqual(v.validate("tata"), DummyEnum.tata)
        self.assertTrue(isinstance(v.validate("tata"), DummyEnum))
        self.assertEqual(v.validate(u"titi"), DummyEnum.titi)
        self.assertTrue(isinstance(v.validate(u"titi"), DummyEnum))
        self.assertEqual(v.validate(u"Other Value"), DummyEnum.popo)
        self.assertTrue(isinstance(v.validate(u"Other Value"), DummyEnum))
        self.assertRaises(ValueError, v.validate, 66)
        self.assertRaises(ValueError, v.validate, None)
        self.assertRaises(ValueError, v.validate, "dummy")
        self.assertRaises(ValueError, v.validate, u"dummy")

        self.assertEqual(v.publish(DummyEnum.toto), u"toto")
        self.assertTrue(isinstance(v.publish(DummyEnum.toto), unicode))
        self.assertEqual(v.publish(DummyEnum.tata), u"tata")
        self.assertEqual(v.publish(DummyEnum.popo), u"Other Value")
        self.assertRaises(ValueError, v.publish, "dummy")
        self.assertRaises(ValueError, v.publish, u"dummy")
        self.assertRaises(ValueError, v.publish, 44)
        self.assertRaises(ValueError, v.publish, None)

        self.assertEqual(v.as_string(DummyEnum.toto), u"toto")
        self.assertTrue(isinstance(v.as_string(DummyEnum.toto), unicode))
        self.assertEqual(v.as_string(DummyEnum.tata), u"tata")
        self.assertEqual(v.as_string(DummyEnum.popo), u"Other Value")
        self.assertRaises(ValueError, v.as_string, "dummy")
        self.assertRaises(ValueError, v.as_string, u"dummy")
        self.assertRaises(ValueError, v.as_string, 44)
        self.assertRaises(ValueError, v.as_string, None)

        v = value.Enum(DummyEnum, DummyEnum.toto)
        self.assertTrue(interface.IValueInfo.providedBy(v))
        self.assertTrue(interface.IValueOptions.providedBy(v))
        self.assertEqual(v.value_type, interface.ValueTypes.string)
        self.assertTrue(v.use_default)
        self.assertEqual(v.default, DummyEnum.toto)
        self.assertTrue(isinstance(v.default, DummyEnum))

        self.assertEqual(v.validate(None), DummyEnum.toto)
        self.assertEqual(v.publish(None), u"toto")
        self.assertTrue(isinstance(v.publish(None), unicode))
        self.assertEqual(v.as_string(None), u"toto")
        self.assertTrue(isinstance(v.as_string(None), unicode))

        v = value.Enum(DummyEnum, default=DummyEnum.tata)
        self.assertTrue(v.use_default)
        self.assertEqual(v.default, DummyEnum.tata)
        self.assertTrue(isinstance(v.default, DummyEnum))

        self.assertEqual(v.validate(None), DummyEnum.tata)
        self.assertEqual(v.publish(None), u"tata")
        self.assertTrue(isinstance(v.publish(None), unicode))
        self.assertEqual(v.as_string(None), u"tata")
        self.assertTrue(isinstance(v.as_string(None), unicode))

    def testBooleanValue(self):
        v = value.Boolean()
        self.assertTrue(interface.IValueInfo.providedBy(v))
        self.assertTrue(interface.IValueOptions.providedBy(v))
        self.assertEqual(v.value_type, interface.ValueTypes.boolean)
        self.assertFalse(v.use_default)
        self.assertTrue(v.is_restricted)

        self.assertEqual(set([o.value for o in v.iter_options()]),
                         set([True, False]))
        self.assertTrue(all(isinstance(o.value, bool)
                            for o in v.iter_options()))
        self.assertEqual(set([o.label for o in v.iter_options()]),
                         set([u"True", u"False"]))
        self.assertTrue(all(isinstance(o.label, unicode)
                            for o in v.iter_options()))

        self.assertEqual(v.validate(True), True)
        self.assertTrue(isinstance(v.validate(True), bool))
        self.assertEqual(v.validate(False), False)
        self.assertEqual(v.validate("True"), True)
        self.assertEqual(v.validate("true"), True)
        self.assertEqual(v.validate("False"), False)
        self.assertEqual(v.validate("false"), False)
        self.assertEqual(v.validate(u"True"), True)
        self.assertEqual(v.validate(u"true"), True)
        self.assertEqual(v.validate(u"False"), False)
        self.assertEqual(v.validate(u"false"), False)
        self.assertRaises(ValueError, v.validate, 1)
        self.assertRaises(ValueError, v.validate, "dummy")
        self.assertRaises(ValueError, v.validate, u"dummy")

        self.assertEqual(v.publish(True), True)
        self.assertTrue(isinstance(v.publish(True), bool))
        self.assertEqual(v.publish(False), False)
        self.assertRaises(ValueError, v.publish, "True")
        self.assertRaises(ValueError, v.publish, u"True")
        self.assertRaises(ValueError, v.publish, 0)

        self.assertEqual(v.as_string(True), u"True")
        self.assertTrue(isinstance(v.as_string(True), unicode))
        self.assertEqual(v.as_string(False), u"False")
        self.assertRaises(ValueError, v.as_string, "True")
        self.assertRaises(ValueError, v.as_string, u"True")
        self.assertRaises(ValueError, v.as_string, 0)

        v = value.Boolean(True)
        self.assertTrue(v.use_default)
        self.assertEqual(v.default, True)
        self.assertTrue(isinstance(v.default, bool))

        self.assertEqual(v.validate(None), True)
        self.assertTrue(isinstance(v.validate(None), bool))
        self.assertEqual(v.publish(None), True)
        self.assertTrue(isinstance(v.publish(None), bool))
        self.assertEqual(v.as_string(None), u"True")
        self.assertTrue(isinstance(v.as_string(None), unicode))

        v = value.Boolean(default=False)
        self.assertTrue(v.use_default)
        self.assertEqual(v.default, False)
        self.assertTrue(isinstance(v.default, bool))

        self.assertEqual(v.validate(None), False)
        self.assertTrue(isinstance(v.validate(None), bool))
        self.assertEqual(v.publish(None), False)
        self.assertTrue(isinstance(v.publish(None), bool))
        self.assertEqual(v.as_string(None), u"False")
        self.assertTrue(isinstance(v.as_string(None), unicode))

    def testEquality(self):
        self.assertTrue(value.Integer() == value.Integer())
        self.assertTrue(value.Integer(14) == value.Integer(14))
        self.assertTrue(value.Integer(12345678901234567890)
                        == value.Integer(12345678901234567890))
        self.assertTrue(value.String() == value.String())
        self.assertTrue(value.String("foo") == value.String("foo"))
        self.assertTrue(value.String("foo") == value.String(u"foo"))
        self.assertTrue(DummyStringOptions() == DummyStringOptions())
        self.assertTrue(value.Enum(DummyEnum) == value.Enum(DummyEnum))
        self.assertTrue(value.Enum(DummyEnum, DummyEnum.toto)
                        == value.Enum(DummyEnum, DummyEnum.toto))
        self.assertTrue(value.Boolean() == value.Boolean())
        self.assertTrue(value.Boolean(False) == value.Boolean(False))

        self.assertFalse(value.Integer() == value.Integer(12))
        self.assertFalse(value.Integer(33) == value.Integer(66))
        self.assertFalse(value.String() == value.String("foo"))
        self.assertFalse(value.String("foo") == value.String("bar"))
        self.assertFalse(value.Enum(DummyEnum)
                         == value.Enum(DummyEnum, DummyEnum.tata))
        self.assertFalse(value.Enum(DummyEnum, DummyEnum.toto)
                         == value.Enum(DummyEnum, DummyEnum.tata))
        self.assertFalse(value.Boolean() == value.Boolean(True))
        self.assertFalse(value.Boolean(True) == value.Boolean(False))

        self.assertFalse(value.Integer() != value.Integer())
        self.assertFalse(value.Integer(14) != value.Integer(14))
        self.assertFalse(value.Integer(12345678901234567890)
                         != value.Integer(12345678901234567890))
        self.assertFalse(value.String() != value.String())
        self.assertFalse(value.String("foo") != value.String("foo"))
        self.assertFalse(value.String("foo") != value.String(u"foo"))
        self.assertFalse(DummyStringOptions() != DummyStringOptions())
        self.assertFalse(value.Enum(DummyEnum) != value.Enum(DummyEnum))
        self.assertFalse(value.Enum(DummyEnum, DummyEnum.toto)
                         != value.Enum(DummyEnum, DummyEnum.toto))
        self.assertFalse(value.Boolean() != value.Boolean())
        self.assertFalse(value.Boolean(False) != value.Boolean(False))

        self.assertTrue(value.Integer() != value.Integer(12))
        self.assertTrue(value.Integer(33) != value.Integer(66))
        self.assertTrue(value.String() != value.String("foo"))
        self.assertTrue(value.String("foo") != value.String("bar"))
        self.assertTrue(value.Enum(DummyEnum)
                        != value.Enum(DummyEnum, DummyEnum.tata))
        self.assertTrue(value.Enum(DummyEnum, DummyEnum.toto)
                        != value.Enum(DummyEnum, DummyEnum.tata))
        self.assertTrue(value.Boolean() != value.Boolean(True))
        self.assertTrue(value.Boolean(True) != value.Boolean(False))
