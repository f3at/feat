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

from zope.interface import implements, classImplements

from feat.common import annotate, container
from feat.models import meta as models_meta

from feat.models.interface import *
from feat.models.interface import IValidator
from feat.interface.serialization import ISnapshotable


meta = models_meta.meta


def label(lable):
    """
    Annotates the IValueInfo label.
    @param label: label of the IValueInfo being defined.
    @type label: str or unicode
    """
    _annotate("label", lable)


def desc(desc):
    """
    Annotates the IValueInfo description.
    @param desc: description of the IValueInfo being defined.
    @type desc: str or unicode
    """
    _annotate("desc", desc)


def value_type(vtype):
    """
    Annotates the IValueInfo value type.
    @param vtype: type of the IValueInfo being defined.
    @type vtype: ValueTypes
    """
    _annotate("value_type", vtype)


def default(default):
    """
    Annotates the IValueInfo default value,
    will be validated at instance creation time.
    @param default: default value of the IValueInfo being defined.
    @type default: Any
    """
    _annotate("default", default)


def option(value, is_default=False, label=None):
    """
    Annotates a possible value for IValueOptions,
    will be validated at instance creation time.
    @param value: a possible value for the IValueOptions being defined.
    @type value: Any
    @param is_default: if the option should be the default value.
    @type is_default: bool
    @param label: option label or None; if none the string representation
                  of the value will be used as label.
    @type value: str or unicode or None
    """
    _annotate("option", value, is_default=is_default, label=label)


def options_only():
    """
    Annotates to enforce the value to be one of the specified options.
    """
    _annotate("options_only")


def allows(value_info):
    """
    Annotate an allowed value info for a collection.
    @param value_info: an allowed value for the collection.
    @type value_info: IValueInfo
    """
    _annotate("allows", value_info)


def is_ordered(flag):
    """Annotate a collection to be ordered.
    @param flag: if the collection order is important.
    @type flag: bool
    """
    _annotate("is_ordered", flag)


def min_size(size):
    """Annotate a collection minimum size.
    @param size: the collection minimum size.
    @type flag: int
    """
    _annotate("min_size", size)


def max_size(size):
    """Annotate a collection maximum size.
    @param size: the collection maximum size.
    @type flag: int
    """
    _annotate("max_size", size)


def _annotate(name, *args, **kwargs):
    method_name = "annotate_" + name
    annotate.injectClassCallback(name, 4, method_name, *args, **kwargs)


class BaseValue(models_meta.Metadata):

    implements(IValueInfo, IValidator)

    _class_label = None
    _class_desc = None
    _class_value_type = None
    _class_use_default = False
    _class_default = None

    ### IValueInfo ###

    @property
    def label(self):
        return self._class_label

    @property
    def desc(self):
        return self._class_desc

    @property
    def value_type(self):
        return self._class_value_type

    @property
    def use_default(self):
        return self._class_use_default

    @property
    def default(self):
        return self._class_default

    def __eq__(self, other):
        if not IValueInfo.providedBy(other):
            return NotSupported
        other = IValueInfo(other)
        if self.value_type != other.value_type:
            return False
        if self.use_default != other.use_default:
            return False
        if self.use_default and (self._default != other.default):
            return False
        if IValueOptions.providedBy(self) != IValueOptions.providedBy(other):
            return False
        if IValueOptions.providedBy(self):
            other = IValueOptions(other)
            other_options = set(other.iter_options())
            self_options = set(self.iter_options())
            if other_options != self_options:
                return False
            if self.is_restricted != other.is_restricted:
                return False
        if IValueRange.providedBy(self) != IValueRange.providedBy(other):
            return False
        if IValueRange.providedBy(self):
            other = IValueRange(other)
            if (self.minimum != other.minimum
                or self.maximum != other.maximum
                or self.increment != other.increment):
                return False
        return True

    def __ne__(self, other):
        eq = self.__eq__(other)
        return eq if eq is NotSupported else not eq

    ### IValidator ###

    def validate(self, value):
        if value is None and self.use_default:
            value = self.default
        return value

    def publish(self, value):
        if value is None and self.use_default:
            value = self.default
        return value

    def as_string(self, value):
        return unicode(self.publish(value))

    ### annotations ###

    @classmethod
    def annotate_label(cls, label):
        """@see: feat.models.value.label"""
        cls._class_label = label

    @classmethod
    def annotate_desc(cls, desc):
        """@see: feat.models.value.desc"""
        cls._class_desc = desc

    @classmethod
    def annotate_value_type(cls, value_type):
        """@see: feat.models.value.value_type"""
        if value_type not in ValueTypes:
            raise ValueError(value_type)
        cls._class_value_type = value_type

    @classmethod
    def annotate_default(cls, default):
        """@see: feat.models.value.default"""
        cls._class_use_default = True
        cls._class_default = default


class _InterfaceValue(BaseValue):

    _value_interface = None

    def validate(self, value):
        new_value = BaseValue.validate(self, value)
        if not self._value_interface.providedBy(value):
            raise ValueError(value)
        return new_value

    def publish(self, value):
        new_value = BaseValue.publish(self, value)
        if not self._value_interface.providedBy(value):
            raise ValueError(value)
        return new_value


class Response(_InterfaceValue):
    """Definition of a model value."""

    _value_interface = IResponse

    value_type(ValueTypes.model)


class Reference(_InterfaceValue):
    """Definition of a model value."""

    _value_interface = IReference

    value_type(ValueTypes.reference)


class Struct(BaseValue):
    """Definition of a model value."""

    _value_interface = ISnapshotable

    value_type(ValueTypes.struct)


class Value(BaseValue):

    _class_options = None
    _class_options_only = False

    def __init__(self, *args, **kwargs):
        label = self._class_label
        desc = self._class_desc
        self._label = unicode(label) if label is not None else None
        self._desc = unicode(desc) if desc is not None else None
        self._value_type = self._class_value_type
        self._options_only = False
        self._options = []
        if self._class_options is not None:
            for v, l in self._class_options:
                self._add_option(v, l)
        self._options_only = self._class_options_only

        self._use_default = self._class_use_default
        self._default = None
        if self._use_default:
            self._default = self._validate_default(self._class_default)

        if "default" in kwargs:
            if len(args) > 0:
                raise ValueError("If the default value is specified "
                                 "as a keyword, no argument are allowed")
            self._set_default(kwargs.pop("default"))
        else:
            if len(args) > 1:
                raise ValueError("Only default value is "
                                 "supported as argument")
            if len(args) > 0:
                self._set_default(args[0])

        if kwargs:
            raise ValueError("Unsupported keyword arguments")


    ### IValueInfo ###

    @property
    def label(self):
        return self._label

    @property
    def desc(self):
        return self._desc

    @property
    def value_type(self):
        return self._value_type

    @property
    def use_default(self):
        return self._use_default

    @property
    def default(self):
        return self._default

    ### IValidator ###

    def validate(self, value):
        value = BaseValue.validate(self, value)
        if self._options_only and not self._has_option(value):
            raise ValueError(value)
        return value

    def publish(self, value):
        value = BaseValue.validate(self, value)
        if self._options_only and not self.has_option(value):
            raise ValueError(value)
        return value

    ### IValueOptions ###

    @property
    def is_restricted(self):
        return self._options_only

    def count_options(self):
        return len(self._options)

    def iter_options(self):
        return iter(self._options)

    def has_option(self, value):
        try:
            return self._has_option(self._validate_option(value))
        except ValueError:
            return False

    def get_option(self, value):
        value = unicode(value)
        try:
            return next((o for o in self._options if o.value == value))
        except StopIteration:
            return None

    ### protected ###

    def _validate_default(self, value):
        return self.validate(value)

    def _validate_option(self, value):
        return self.validate(value)

    def _has_option(self, value):
        try:
            next((o for o in self._options if o.value == value))
            return True
        except StopIteration:
            return False

    def _set_default(self, default):
        self._default = self._validate_default(default)
        self._use_default = True

    def _add_option(self, value, label=None):
        # Disable options_only to be able to validate the value
        options_only = self._options_only
        self._options_only = False
        try:
            option = ValueOption(self._validate_option(value), label)
            self._options.append(option)
        finally:
            self._options_only = options_only

    ### annotations ###

    @classmethod
    def annotate_option(cls, value, is_default=False, label=None):
        """@see: feat.models.value.option"""
        if cls._class_options is None:
            cls._class_options = container.MroList("_mro_options")
            classImplements(cls, IValueOptions)
        if is_default:
            cls._class_default = value
            cls._class_use_default = True
        cls._class_options.append((value, label))

    @classmethod
    def annotate_options_only(cls):
        """@see: feat.models.value.options_only"""
        cls._class_options_only = True


class ValueOption(object):
    """Pair of value/label defining a possible option.
    @see: feat.models.interface.IValueOption"""

    implements(IValueOption)

    def __init__(self, value, label=None):
        self._value = value
        self._label = unicode(label) if label is not None else unicode(value)

    ### IValueOption ###

    @property
    def value(self):
        return self._value

    @property
    def label(self):
        return self._label

    def __eq__(self, other):
        if not IValueOption.providedBy(other):
            return False
        return (self._value == other.value
                and self._label == other.label)

    def __ne__(self, other):
        return not self.__eq__(other)

    def __hash__(self):
        return hash(self._value) ^ hash(self._label)


class String(Value):
    """String value definition."""

    value_type(ValueTypes.string)

    ### overridden ###

    def validate(self, value):
        """
        Accepts: str, unicode
        Returns: unicode
        """
        val = value
        if isinstance(val, str):
            #FIXME: unsafe decoding
            val = unicode(value)
        val = super(String, self).validate(val)
        if not isinstance(val, unicode):
            raise ValueError(value)
        return val

    def publish(self, value):
        """
        Accepts: unicode, str
        Returns: unicode
        """
        val = value
        if isinstance(val, str):
            #FIXME: unsafe decoding
            val = unicode(value)
        val = super(String, self).publish(val)
        if not isinstance(val, unicode):
            raise ValueError(value)
        return val


class Integer(Value):
    """Definition of an basic integer value."""

    value_type(ValueTypes.integer)

    ### overridden ###

    def validate(self, value):
        """
        Accepts: int, long, str, unicode
        Returns: int, long
        """
        if isinstance(value, (str, unicode)):
            value = int(value)
        value = super(Integer, self).validate(value)
        if not isinstance(value, (int, long)):
            raise ValueError(value)
        return value

    def publish(self, value):
        """
        Accepts: int, long
        Returns: int, long
        """
        value = super(Integer, self).publish(value)
        if not isinstance(value, (int, long)):
            raise ValueError(value)
        return value


class Boolean(Value):
    """Definition of an basic integer value."""

    value_type(ValueTypes.boolean)
    option(True, label="True")
    option(False, label="False")
    options_only()

    ### overridden ###

    def validate(self, value):
        """
        Accepts: str, unicode, bool
        Returns: bool
        """
        if isinstance(value, bool):
            return value
        if isinstance(value, (str, unicode)):
            if value.lower() == "true":
                value = True
            elif value.lower() == "false":
                value = False
            else:
                raise ValueError(value)
        value = super(Boolean, self).validate(value)
        if not isinstance(value, bool):
            raise ValueError(value)
        return value

    def publish(self, value):
        value = super(Boolean, self).publish(value)
        if not isinstance(value, bool):
            raise ValueError(value)
        return value


class Enum(Value):
    """Definition of integer value with a fixed
    set of possible values taken from an enumeration."""

    value_type(ValueTypes.string)
    options_only()

    implements(IValueOptions)

    def __init__(self, enum, *args, **kwargs):
        self._enum = enum
        Value.__init__(self, *args, **kwargs)
        for i in enum:
            self._add_option(i)

    ### IValidator ###

    def validate(self, value):
        if value is None and self._use_default:
            value = self._default
        if isinstance(value, (str, unicode, int)):
            if value in self._enum:
                return self._enum[value]
        if isinstance(value, int):
            if value in self._enum:
                return unicode(self._enum[value].name)
        raise ValueError(value)

    def publish(self, value):
        if value is None and self._use_default:
            value = self._default
        if isinstance(value, (str, unicode)):
            if value in self._enum:
                return unicode(value)
        if isinstance(value, int):
            if value in self._enum:
                return unicode(self._enum[value].name)
        raise ValueError(value)

    ### overridden ###

    def _validate_option(self, value):
        return unicode(self.validate(value).name)

    def _validate_default(self, value):
        return unicode(self.validate(value).name)

    def _add_option(self, value, label=None):
        if isinstance(value, self._enum):
            value = unicode(value.name)
        return Value._add_option(self, value, label)


class Collection(Value):

    implements(IValueCollection)

    _class_allowed_types = container.MroList("_mro_allowed_types")
    _class_is_ordered = True
    _class_min_size = None
    _class_max_size = None

    value_type(ValueTypes.collection)

    ### IValueCollection ###

    @property
    def allowed_types(self):
        return list(self._class_allowed_types)

    @property
    def is_ordered(self):
        return self._class_is_ordered

    @property
    def min_size(self):
        return self._class_min_size

    @property
    def max_size(self):
        return self._class_max_size

    ### overridden ###

    def validate(self, value):
        return self._convert(value, "validate")

    def publish(self, value):
        return self._convert(value, "publish")

    ### annotations ###

    @classmethod
    def annotate_allows(cls, value_info):
        """@see: feat.models.value.allows"""
        value_info = _validate_value_info(value_info)
        cls._class_allowed_types.append(value_info)

    @classmethod
    def annotate_is_ordered(cls, flag):
        """@see: feat.models.value.is_ordered"""
        cls._class_is_ordered = _validate_flag(flag)

    @classmethod
    def annotate_min_size(cls, size):
        """@see: feat.models.value.min_size"""
        cls._class_min_size = _validate_size(size)

    @classmethod
    def annotate_max_size(cls, size):
        """@see: feat.models.value.max_size"""
        cls._class_max_size = _validate_size(size)

    ### private ###

    def _convert(self, value, method_name):
        if isinstance(value, (str, unicode)):
            raise ValueError(value)
        try:
            all_values = list(value)
        except TypeError:
            raise ValueError(value)
        result = []
        if self._class_min_size is not None:
            if len(all_values) < self._class_min_size:
                raise ValueError(value)
        if self._class_max_size is not None:
            if len(all_values) > self._class_max_size:
                raise ValueError(value)
        allowed_types = list(self._class_allowed_types)
        for v in all_values:
            for allowed in allowed_types:
                try:
                    result.append(getattr(allowed, method_name)(v))
                    break
                except ValueError:
                    continue
            else:
                raise ValueError(value)
        return result


### private ###


def _validate_value_info(value_info):
    return IValueInfo(value_info)


def _validate_size(size):
    return int(size)


def _validate_flag(flag):
    return bool(flag)
