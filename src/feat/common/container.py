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
import heapq

from zope.interface import implements, classProvides

from feat.common import serialization
from feat.interface.generic import *


__all__ = ("MroDict", "Empty", "ExpDict", "ExpQueue")

PRECISION = 1e3
MAX_LAZY_PACK_PER_SECOND = 1


class MroDict(object):
    """
    I'm an dictionary which is ment to be used as a class attribute.
    I'm aware of MRO and show different values depending from which class
    i'm accessed.

    NOTE: Keep in mind that accessible mro dictionary in results in two
    dictionaries being instantiated. The is expensive operation, in case of
    performing multiple operations in single method it is recommended to
    assign it to local variable.
    """

    def __init__(self, tag):
        self._tag = tag

    ### descriptor protocol ###

    def __get__(self, obj, owner):
        klasses = owner.mro()
        klasses.reverse()

        kwargs = dict()
        for klass in klasses:
            kwargs.update(getattr(klass, self._tag, dict()))
        return ProxyDict(self._get_tag(owner), kwargs)

    def __set__(self, instance, value):
        return NotImplemetedError(
            "You are doing something you shouldn't be doing")

    def __delete__(self, instance):
        return NotImplemetedError(
            "You are doing something you shouldn't be doing")

    ### endof descriptor protocol ###

    def _get_tag(self, cls):
        if self._tag not in cls.__dict__:
            setattr(cls, self._tag, dict())
        return getattr(cls, self._tag)


class ProxyDict(dict):
    '''
    Delegates mutating methods to the owner which is part of the big object.
    '''

    def __init__(self, owner, kwargs):
        dict.__init__(self, kwargs.iteritems())
        self._owner = owner

    def __setitem__(self, key, value):
        self._owner.__setitem__(key, value)
        dict.__setitem__(self, key, value)

    def __delitem__(self, key):
        self._owner.__delitem__(key)
        dict.__delitem__(self, key)


class Empty(Exception):
    pass


class ExpBase(object):

    ### ISerializable Method ###

    def snapshot(self):
        """Should return a python structure."""

    def recover(self, snapshot):
        """Should recover from a snapshot."""

    def restored(self):
        """Called when everything has been recovered."""

    ### IRestorator Method ###

    @classmethod
    def prepare(cls):
        return cls.__new__(cls)


@serialization.register
class ExpDict(ExpBase):
    """
    WARNING: - Getting the length and therefore construct like
               "if exp_dict: ..." or "bool(exp_dict)"
               will iterate over all elements.
             - Comparison operations are very expensive.
    """

    DEFAULT_MAX_SIZE = 1000

    type_name = "xdict"

    classProvides(serialization.IRestorator)
    implements(serialization.ISerializable)

    __slots__ = ("_time", "_items", "_max_size", "_last_pack")

    def __init__(self, time_provider, max_size=None):
        '''Create an expiration dictionary.
        @param time_provider: who provide the time
        @type time_provider: L{ITimeProvider}
        @param max_size: maximum size before forced packing
        @type max_size: int'''
        self._time = ITimeProvider(time_provider)
        self._items = {} # {KEY: ExpItem(TIME, VALUE)}
        self._max_size = max_size or self.DEFAULT_MAX_SIZE
        self._last_pack = 0

    def clear(self):
        '''Removes all items from the dictionary.'''
        self._items.clear()

    def pack(self):
        '''Packs the dictionary by removing all expired items.'''
        self._pack(self._time.get_time())

    def set(self, key, value=None, expiration=None, relative=False):
        '''Adds an entry to the dictionary with specified expiration and value.
        @param key: unique key of the entry, used to remove or test ownership
        @type key: any immutable
        @param value: black box associated with the key
        @type value: any python structure or L{ISerializable}
        @param expiration: the time at which the entry will expire.
        @type expiration: float
        @param relative: if the specified expiration time is relative
                         to EPOC UTC or from now.
        @type relative: bool
        @return: nothing'''
        self._lazy_pack()
        if expiration is not None:
            now = self._time.get_time()
            if relative:
                expiration = now + expiration
            if expiration <= now:
                return
        self._items[key] = ExpItem(expiration, value)

    def remove(self, key):
        '''Removes the dictionary entry with with specified key .
        @param key: unique key of the entry, used to remove or test ownership
        @type key: any immutable
        @return: item value
        @rtype: any python structure or L{ISerializable}'''
        self._lazy_pack()
        now = self._time.get_time()
        if self._items:
            item = self._items.pop(key)
            if item.exp is None or item.exp > now:
                return item.value
        raise KeyError(key)

    def pop(self, key, *default):
        '''Pops and returns the dictionary entry with with specified key.
        @param key: unique key of the entry, used to remove or test ownership
        @type key: any immutable
        @return: value
        @rtype: any python structure or L{ISerializable}'''
        self._lazy_pack()
        now = self._time.get_time()
        if self._items:
            try:
                item = self._items.pop(key)
                if item.exp is None or item.exp > now:
                    return item.value
                raise KeyError(key)
            except KeyError:
                if len(default) == 1:
                    return default[0]
                else:
                    raise

    def get(self, key, default=None):
        '''Retrieve value from the entry with specified key.
        @param key: unique key of the entry, used to remove or test ownership
        @type key: any immutable
        @param default: value returned if no entry is found with specified key
        @type default: any python structure or L{ISerializable}
        @return: entry value or default value
        @rtype: any python structure or L{ISerializable}'''
        item = self._get_item(key)
        return default if item is None else item.value

    def iterkeys(self):
        '''Returns an iterator over the dictionary keys.'''
        self._lazy_pack()
        now = self._time.get_time()
        for key, item in self._items.iteritems():
            if item.exp is None or item.exp > now:
                yield key
                now = self._time.get_time()

    def itervalues(self):
        '''Returns an iterator over the dictionary values.'''
        self._lazy_pack()
        now = self._time.get_time()
        for item in self._items.itervalues():
            if item.exp is None or item.exp > now:
                yield item.value
                now = self._time.get_time()

    def values(self):
        return list(self.itervalues())

    def keys(self):
        return list(self.iterkeys())

    def iteritems(self):
        '''Returns an iterator over tuples (key, value).'''
        self._lazy_pack()
        now = self._time.get_time()
        for key, item in self._items.iteritems():
            if item.exp is None or item.exp > now:
                yield key, item.value
                now = self._time.get_time()

    def size(self):
        '''Returns the current size counting expired elements.'''
        return len(self._items)

    def __setitem__(self, key, value):
        self._lazy_pack()
        self._items[key] = ExpItem(None, value)

    def __getitem__(self, key):
        item = self._get_item(key)
        if item is not None:
            return item.value
        raise KeyError(key)

    def __delitem__(self, key):
        item = self._get_item(key)
        if item is not None:
            del self._items[key]
            return
        raise KeyError(key)

    def __contains__(self, key):
        return self._get_item(key) is not None

    def __iter__(self):
        return self.iterkeys()

    def __len__(self):
        now = self._time.get_time()
        return len([i for i in self._items.itervalues()
                    if i.exp is None or i.exp > now])

    def __eq__(self, other):
        if not issubclass(type(other), type(self)):
            return NotImplemented
        now = self._time.get_time()
        a = [(k, i.pri, i.value)
             for k, i in self._items.iteritems()
             if i.exp is None or i.exp > now]
        b = [(k, i.pri, i.value)
             for k, i in other._items.iteritems()
             if i.exp is None or i.exp > now]
        a.sort()
        b.sort()
        return a == b

    def __ne__(self, other):
        eq = self.__eq__(other)
        return eq if eq == NotImplemented else not eq

    ### ISerializable Method ###

    def snapshot(self):
        return (self._time, self._max_size,
                dict([(k, i.snapshot()) for k, i in self._items.iteritems()]))

    def recover(self, snapshot):
        self._time, self._max_size, data = snapshot
        self._items = dict([(k, ExpItem.restore(s))
                            for k, s in data.iteritems()])
        self._last_pack = 0

    ### Private Methods ###

    def _lazy_pack(self):
        if len(self._items) > self._max_size:
            now = self._time.get_time()
            # Regulate lazy packing rate
            if (now - self._last_pack) >= (1.0 / MAX_LAZY_PACK_PER_SECOND):
                self._pack(now)

    def _pack(self, now):
        self._items = dict([(k, i) for k, i in self._items.iteritems()
                            if i.exp is None or i.exp > now])
        self._last_pack = now

    def _get_item(self, key):
        self._lazy_pack()
        now = self._time.get_time()
        item = self._items.get(key, None)
        if item is not None:
            if item.exp is None or item.exp > now:
                return item
            del self._items[key]
        return None


@serialization.register
class ExpQueue(ExpBase):
    """
    WARNING: - Getting the length and therefore construct like
               "if exp_dict: ..." or "bool(exp_dict)"
               will iterate over all elements.
             - Comparison operations are very expensive.
    """

    DEFAULT_MAX_SIZE = 1000

    type_name = "xqueue"

    classProvides(serialization.IRestorator)
    implements(serialization.ISerializable)

    __slots__ = ("_time", "_heap", "_max_size", "_last_pack")

    def __init__(self, time_provider, max_size=None):
        '''Create an expiration queue.
        @param time_provider: who provide the time
        @type time_provider: L{ITimeProvider}
        @param max_size: maximum size before forced packing
        @type max_size: int'''
        self._time = ITimeProvider(time_provider)
        self._heap = []
        self._max_size = max_size or self.DEFAULT_MAX_SIZE
        self._last_pack = 0

    def pack(self):
        '''Packs the set by removing all expired items.'''
        self._pack(self._time.get_time())

    def clear(self):
        '''Removes all the values from the queue.'''
        self._heap = []

    def add(self, value, expiration=None, relative=False):
        '''Adds an entry to the queue with specified expiration and value.
        @param value: black box associated with the key
        @type value: any python structure or L{ISerializable}
        @param expiration: the time at which the entry will expire.
        @type expiration: float
        @param relative: if the specified expiration time is relative
                         to EPOC UTC or from now.
        @type relative: bool
        @return: nothing'''
        self._lazy_pack()
        now = self._time.get_time()
        if expiration is not None:
            now = self._time.get_time()
            if relative:
                expiration = now + expiration
            if expiration <= now:
                return
        heapq.heappush(self._heap, ExpItem(expiration, value))

    def pop(self):
        '''Pops and returns the value with the smaller expiration.
        @returns: value
        @rtype: any python structure or L{ISerializable}'''
        self._lazy_pack()
        now = self._time.get_time()
        while True:
            try:
                item = heapq.heappop(self._heap)
                if item.exp is None or item.exp > now:
                    return item.value
            except IndexError:
                raise Empty()

    def size(self):
        '''Returns the current size counting expired values.'''
        return len(self._heap)

    def __iter__(self):
        '''Returns an iterator over queue's values.'''
        self._lazy_pack()
        now = self._time.get_time()
        for item in iter(self._heap):
            if item.exp is None or item.exp > now:
                yield item.value
                now = self._time.get_time()

    def __len__(self):
        now = self._time.get_time()
        return len([i for i in self._heap
                    if i.exp is None or i.exp > now])

    def __eq__(self, other):
        if not issubclass(type(other), type(self)):
            return NotImplemented
        now = self._time.get_time()
        a = [(i.pri, i.value)
             for i in self._heap
             if i.exp is None or i.exp > now]
        b = [(i.pri, i.value)
             for i in other._heap
             if i.exp is None or i.exp > now]
        a.sort()
        b.sort()
        return a == b

    def __ne__(self, other):
        eq = self.__eq__(other)
        return eq if eq == NotImplemented else not eq

    ### ISerializable Method ###

    def snapshot(self):
        now = self._time.get_time()
        return self._time, [i.snapshot()
                            for i in self._heap
                            if i.exp is None or i.exp > now]

    def recover(self, snapshot):
        self._time, data = snapshot
        self._heap = [ExpItem.restore(d) for d in data]
        self._last_pack = 0

    ### Private Methods ###

    def _lazy_pack(self):
        if len(self._heap) > self._max_size:
            now = self._time.get_time()
            # Regulate lazy packing rate
            if (now - self._last_pack) >= (1.0 / MAX_LAZY_PACK_PER_SECOND):
                self._pack(now)

    def _pack(self, now):
        new_heap = [i for i in self._heap if i.exp is None or i.exp > now]
        heapq.heapify(new_heap)
        self._heap = new_heap
        self._last_pack = now


## Private Stuff ###


class ExpItem(object):
    '''
    Encapsulate an item with expiration.
    It compares with other ExpItem using expiration time
    up to a resolution of a millisecond.
    In other words, if ExpItem have an expiration difference
    of less than a millisecond they will be evaluated equal.
    '''

    __slots__ = ("exp", "value")

    @classmethod
    def restore(cls, snapshot):
        pri, value = snapshot
        exp = None if pri is None else float(pri) / PRECISION
        return cls(exp, value)

    def __init__(self, exp, value):
        self.exp = exp
        self.value = value

    @property
    def pri(self):
        if self.exp is None:
            return None
        return int(round(self.exp * PRECISION))

    def __cmp__(self, other):
        # None has always the least priority
        if self.exp is None:
            if other.exp is None:
                return 0
            return 1
        elif other.exp is None:
            return -1

        diff = (self.exp * PRECISION) - (other.exp * PRECISION)
        return int(round(diff))

    def snapshot(self):
        return self.pri, self.value

### Private Stuff ###
