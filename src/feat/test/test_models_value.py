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

from . import common


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


class TestModelsValue(common.TestCase):

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
        self.assertRaises(ValueError, v.validate, None)

        v = value.String(default="FOO")
        self.assertTrue(v.use_default)
        self.assertEqual(v.default, u"FOO")
        self.assertTrue(isinstance(v.default, unicode))
        self.assertEqual(v.validate(None), u"FOO")

        v = value.String("FOO")
        self.assertTrue(v.use_default)
        self.assertEqual(v.default, u"FOO")
        self.assertTrue(isinstance(v.default, unicode))
        self.assertEqual(v.validate(None), u"FOO")

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
        self.assertEqual(v.validate(""), u"")
        self.assertEqual(v.validate(None), u"spam")
        self.assertTrue(isinstance(v.validate(None), unicode))

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
        self.assertEqual(v.validate(None), u"bacon")
        self.assertTrue(isinstance(v.validate(None), unicode))
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
        self.assertTrue(isinstance(v.get_option(u"bacon").value, unicode))
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
        self.assertRaises(ValueError, v.validate, 1.5)
        self.assertRaises(ValueError, v.validate, "spam")

        v = value.String(default="FOO")
        self.assertTrue(v.use_default)
        self.assertEqual(v.default, u"FOO")
        self.assertTrue(isinstance(v.default, unicode))
        self.assertEqual(v.validate(None), u"FOO")

    def testEnumValue(self):
        v = value.Enum(DummyEnum)
        self.assertTrue(interface.IValueInfo.providedBy(v))
        self.assertTrue(interface.IValueOptions.providedBy(v))
        self.assertEqual(v.value_type, interface.ValueTypes.integer)
        self.assertFalse(v.use_default)

        self.assertEqual([o.value for o in v.iter_options()],
                         [0, 1, 2, 42])
        self.assertEqual([o.label for o in v.iter_options()],
                         [u"toto", u"tata", u"titi", u"Other Value"])

        self.assertEqual(v.validate(0), 0)
        self.assertEqual(v.validate(42), 42)
        self.assertEqual(v.validate("tata"), 1)
        self.assertEqual(v.validate("titi"), DummyEnum.titi)
        self.assertEqual(v.validate(u"Other Value"), 42)

    def testEquality(self):
        self.assertTrue(value.Integer() == value.Integer())
        self.assertTrue(value.String() == value.String())
        self.assertTrue(value.Enum(DummyEnum) == value.Enum(DummyEnum))
        self.assertFalse(value.String() == value.String("foo"))
        self.assertTrue(value.String("foo") == value.String("foo"))
        self.assertTrue(DummyStringOptions() == DummyStringOptions())

        self.assertFalse(value.Integer() != value.Integer())
        self.assertFalse(value.String() != value.String())
        self.assertFalse(value.Enum(DummyEnum) != value.Enum(DummyEnum))
        self.assertTrue(value.String() != value.String("foo"))
        self.assertFalse(value.String("foo") != value.String("foo"))
        self.assertFalse(DummyStringOptions() != DummyStringOptions())
