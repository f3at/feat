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
# -*- Mode: Python -*-
# vi:si:et:sw=4:sts=4:ts=4
from twisted.internet import defer
from zope.interface import implements

from feat.test import common
from feat.agents.base import resource, descriptor
from feat.common import time
from feat.interface import journal
from feat.common import fiber

from feat.common.container import *
from feat.common import serialization
from feat.common.serialization import base, pytree
from feat.interface.generic import *

from . import common

from feat.agents.base.resource import *


class Common(object):

    def _assert_allocated(self, expected):
        '''
        Returns allocations & preallocations & modifications
        '''
        al = self.resources.allocated()
        self.assertEqual(expected, al.values())

    def _assert_preallocated(self, expected):
        al = self.resources.preallocated()
        self.assertEqual(expected, al)

    def _assert_resource(self, expc, alloc_id):
        alloc = self.resources.get_allocation(alloc_id)

        self.assertEqual(set(expc), set(alloc.alloc.keys()))
        for k, v in expc.items():
            self.assertEqual(v, alloc.alloc[k].value)


@serialization.register
class DummyAgent(serialization.Serializable, common.DummyRecorderNode,
        common.Mock):

    type_name = "time-provider"

    implements(ITimeProvider)

    def __init__(self, test_case, allocations=None, current=None):
        self.time = current if current is not None else time.time()
        common.DummyRecorderNode.__init__(self, test_case)
        common.Mock.__init__(self)
        self.descriptor = descriptor.Descriptor(allocations=allocations)

    def get_time(self):
        return self.time

    ### ISerailizable override ###

    def snapshot(self):
        return self.time

    def recover(self, snapshot):
        self.time = snapshot

    def get_descriptor(self):
        return self.descriptor

    @common.Mock.record
    def update_descriptor(self, method, allocation):
        assert callable(method)
        method(self.descriptor, allocation)
        return defer.succeed(allocation)


@common.attr(timescale=0.05)
class PortResourceTest(common.TestCase, Common):

    implements(journal.IRecorderNode)

    timeout = 1

    def setUp(self):
        self.allocations = dict()
        self.agent = DummyAgent(self, self.allocations)
        self.resources = resource.Resources(self.agent)

        self.resources.define('streamer', resource.Range, 1000, 1004)
        self.resources.define('slots', resource.Range, 1000, 1004)

    @defer.inlineCallbacks
    def testGettingDeltas(self):
        alloc = yield self.resources.allocate(streamer=3)
        delta = yield self.resources.get_allocation_delta(alloc.id, streamer=5)
        self.assertEqual(dict(streamer=('add', 2)), delta)
        delta = yield self.resources.get_allocation_delta(alloc.id)
        self.assertEqual(dict(streamer=('release', 3)), delta)
        delta = yield self.resources.get_allocation_delta(alloc.id, slots=4)
        exp = dict(streamer=('release', 3), slots=('add', 4))
        self.assertEqual(exp, delta)

        # now bad requests
        d = self.resources.get_allocation_delta(alloc.id, unknown=4)
        self.assertFailure(d, resource.UnknownResource)
        yield d

    @defer.inlineCallbacks
    def testSimpleAllocate(self):
        alloc = yield self.resources.allocate(streamer=3)
        res = alloc.alloc['streamer']
        self.assertIsInstance(res, resource.AllocatedRange)
        self.assertEqual(set([1000, 1001, 1002]), res.values)
        self._assert_allocated([[], [1000, 1001, 1002]])

    @defer.inlineCallbacks
    def testOverallocateAndFragmenting(self):
        alloc1 = yield self.resources.preallocate(streamer=3)
        alloc2 = yield self.resources.preallocate(streamer=3)
        self.assertTrue(alloc2 is None)
        self.assertFalse(alloc1 is None)
        yield self.resources.confirm(alloc1.id)
        self._assert_allocated([[], [1000, 1001, 1002]])

        alloc = yield self.resources.allocate(streamer=1)
        self._assert_allocated([[], [1000, 1001, 1002, 1003]])
        yield self.resources.allocate(streamer=1)
        self._assert_allocated([[], [1000, 1001, 1002, 1003, 1004]])
        yield self.resources.release(alloc.id)
        self._assert_allocated([[], [1000, 1001, 1002, 1004]])

    @defer.inlineCallbacks
    def testModifing(self):
        alloc1 = yield self.resources.allocate(streamer=3)
        self._assert_allocated([[], [1000, 1001, 1002]])
        mod = yield self.resources.premodify(alloc1.id,
            streamer=('release', 1000, 'add', 1))
        self._assert_allocated([[], [1000, 1001, 1002, 1003]])
        yield self.resources.confirm(mod.id)
        self._assert_allocated([[], [1001, 1002, 1003]])

        n = yield self.resources.premodify(alloc1.id,
                                           streamer=('add_specific', 1002))
        self.assertTrue(n is None)

        mod = yield self.resources.premodify(alloc1.id,
                                             streamer=('add', 2))
        self._assert_allocated([[], [1000, 1001, 1002, 1003, 1004]])
        # now expire
        self.agent.time += 15
        self._assert_allocated([[], [1001, 1002, 1003]])


@common.attr(timescale=0.05)
class ResourcesTest(common.TestCase, Common):

    implements(journal.IRecorderNode)

    timeout = 1

    def setUp(self):

        self.allocations = dict()
        self.agent = DummyAgent(self, self.allocations)
        self.resources = resource.Resources(self.agent)

        self.resources.define('a', resource.Scalar, 5)
        self.resources.define('b', resource.Scalar, 6)

    def testCheckingEmptyAllocations(self):
        al = self.resources.allocated()
        self.assertEqual(['a', 'b'], al.keys())
        self.assertEqual([0, 0], al.values())

    @defer.inlineCallbacks
    def testPreallocationExpires(self):
        modification = yield self.resources.preallocate(a=3, b=4)
        self.assertIsInstance(modification, resource.Allocation)

        self._assert_allocated([3, 4])

        self.agent.time += 15

        self._assert_allocated([0, 0])

    @defer.inlineCallbacks
    def testPreallocationRelease(self):
        allocation = yield self.resources.preallocate(a=3)
        self._assert_allocated([3, 0])
        self._assert_preallocated({'a': 3, 'b': 0})
        self.assertCalled(self.agent, 'update_descriptor', times=0)
        yield self.resources.release(allocation.id)
        self._assert_allocated([0, 0])
        self._assert_preallocated({'a': 0, 'b': 0})
        self.assertCalled(self.agent, 'update_descriptor', times=0)

    @defer.inlineCallbacks
    def testPremodifyRelease(self):
        allocation = yield self.resources.allocate(a=3, b=2)
        allocation2 = yield self.resources.allocate(b=1)

        modification = yield \
            self.resources.premodify(allocation_id=allocation.id, a=1, b=1)

        self._assert_allocated([4, 4])
        self._assert_preallocated({'a': 1, 'b': 1})
        yield self.resources.release(modification.id)
        self._assert_allocated([3, 3])
        self._assert_preallocated({'a': 0, 'b': 0})

    @defer.inlineCallbacks
    def testCannotOverallocate(self):
        allocation = yield self.resources.preallocate(a=10)
        self.assertTrue(allocation is None)
        self._assert_allocated([0, 0])
        self.assertCalled(self.agent, 'update_descriptor', times=0)

    @defer.inlineCallbacks
    def testAllocateThrowsOnOverflow(self):
        yield self.assertFails(resource.NotEnoughResource,
                                self.resources.allocate, a=10)
        self.assertCalled(self.agent, 'update_descriptor', times=0)

    @defer.inlineCallbacks
    def testIncorrectAllocation(self):
        yield self.assertFails(resource.DeclarationError,
                                self.resources.allocate, a='sth stupupid')
        yield self.assertFails(resource.DeclarationError,
                               self.resources.preallocate, a='sth stupupid')
        yield self.assertFails(resource.UnknownResource,
                                self.resources.allocate, unknown=4)
        yield self.assertFails(resource.UnknownResource,
                               self.resources.preallocate, unknown=4)
        self.assertCalled(self.agent, 'update_descriptor', times=0)

    @defer.inlineCallbacks
    def testGettingRealAllocation(self):
        allocation = yield self.resources.allocate(a=3)
        self._assert_allocated([3, 0])
        self.assertEqual(2, self.resources._get_state().id_autoincrement)
        self.assertCalled(self.agent, 'update_descriptor')
        yield self.resources.release(allocation.id)
        self.assertCalled(self.agent, 'update_descriptor', times=2)
        self._assert_allocated([0, 0])

    @defer.inlineCallbacks
    def testPreallocatingAndConfirming(self):
        allocation = yield self.resources.preallocate(a=3)
        self._assert_allocated([3, 0])
        self._assert_preallocated({'a': 3, 'b': 0})
        self.assertCalled(self.agent, 'update_descriptor', times=0)
        yield self.resources.confirm(allocation.id)
        self.assertCalled(self.agent, 'update_descriptor', times=1)

    @defer.inlineCallbacks
    def testMultiplePreallocations(self):
        allocation1 = yield self.resources.preallocate(a=1)
        allocation2 = yield self.resources.preallocate(a=1)
        allocation3 = yield self.resources.preallocate(a=1)
        allocation4 = yield self.resources.preallocate(a=1)
        allocation5 = yield self.resources.preallocate(a=1)
        self._assert_allocated([5, 0])
        self._assert_preallocated({'a': 5, 'b': 0})

    @defer.inlineCallbacks
    def testPrellocateAlocateModify(self):
        allocation1 = yield self.resources.allocate(a=1)
        allocation2 = yield self.resources.preallocate(b=1)
        allocation3 = yield self.resources.preallocate(a=1)
        allocation4 = yield self.resources.allocate(b=1)
        modification = yield \
            self.resources.premodify(allocation_id=allocation1.id, a=1, b=1)
        self._assert_allocated([3, 3])
        self._assert_preallocated({'a': 2, 'b': 2})

    def testBadDefine(self):
        return self.assertAsyncFailure(None, resource.DeclarationError,
                                       self.resources.define, 'c',
                                       resource.Scalar, 'not int')

    @defer.inlineCallbacks
    def testAllocationExists(self):
        allocation = yield self.resources.allocate(a=3)
        self.assertTrue(self.resources.check_allocated(allocation.id))

    @defer.inlineCallbacks
    def testPremodifyUnknownId(self):
        allocation = yield self.resources.allocate(a=3)

        d = defer.succeed(None)
        d = self.assertAsyncFailure(d, (resource.AllocationNotFound, ),
                fiber.maybe_fiber, self.resources.premodify,
                allocation_id=100, a=1)
        yield d

    @defer.inlineCallbacks
    def testPremodifyUnknownIdPreallocate(self):
        allocation = yield self.resources.preallocate(a=3)

        d = defer.succeed(None)
        d = self.assertAsyncFailure(d, (resource.AllocationNotFound, ),
                fiber.maybe_fiber, self.resources.premodify,
                allocation_id=100, a=1)
        yield d

    @defer.inlineCallbacks
    def testPremodifySuccess(self):
        allocation = yield self.resources.allocate(a=3, b=2)
        allocation2 = yield self.resources.allocate(b=1)
        # Resources {a:5 b:6}
        modification = yield \
            self.resources.premodify(allocation_id=allocation.id, a=1, b=1)

        self._assert_allocated([4, 4])
        self._assert_preallocated({'a': 1, 'b': 1})

    @defer.inlineCallbacks
    def testApplyModificationSuccess(self):
        allocation = yield self.resources.allocate(a=3, b=2)
        self.assertCalled(self.agent, 'update_descriptor', times=1)
        allocation2 = yield self.resources.allocate(b=1)
        self.assertCalled(self.agent, 'update_descriptor', times=2)
        modification = yield \
            self.resources.premodify(allocation_id=allocation.id, a=1, b=1)
        self._assert_preallocated({'a': 1, 'b': 1})
        # apply modification
        yield self.resources.confirm(modification.id)
        self.assertCalled(self.agent, 'update_descriptor', times=3)

        self._assert_allocated([4, 4])
        self._assert_preallocated({'a': 0, 'b': 0})
        self._assert_resource({'a': 4, 'b': 3}, allocation.id)

    @defer.inlineCallbacks
    def testPremodifyMultipleModifications(self):
        allocation = yield self.resources.allocate(a=3, b=2)
        allocation2 = yield self.resources.allocate(b=1)
        modification = yield \
            self.resources.premodify(allocation_id=allocation.id, a=1, b=1)
        yield self.resources.confirm(modification.id)
        # premodify again
        modification2 = yield \
                self.resources.premodify(allocation_id=allocation2.id, a=1)
        self._assert_allocated([5, 4])
        self._assert_preallocated({'a': 1, 'b': 0})

    @defer.inlineCallbacks
    def testPremodifyOverallocate(self):
        allocation = yield self.resources.allocate(a=3, b=2)
        allocation2 = yield self.resources.allocate(b=1)
        modification = yield \
            self.resources.premodify(allocation_id=allocation.id, a=1, b=1)
        modification2 = yield \
                self.resources.premodify(allocation_id=allocation2.id, a=1)
        self._assert_allocated([5, 4])
        self._assert_preallocated({'a': 2, 'b': 1})
        yield self.resources.confirm(modification.id)

        modification3 = yield \
            self.resources.premodify(allocation_id=allocation.id, a=2)
        self.assertTrue(modification3 is None)

        self._assert_allocated([5, 4])
        self._assert_preallocated({'a': 1, 'b': 0})

    @defer.inlineCallbacks
    def testPremodifyOverallocate2(self):
        allocation = yield self.resources.allocate(b=2)
        allocation2 = yield self.resources.allocate(b=1)
        modification = yield \
            self.resources.premodify(allocation_id=allocation.id, a=1, b=1)
        yield self.resources.confirm(modification.id)
        modification2 = yield \
                self.resources.premodify(allocation_id=allocation2.id, a=1)
        preallocation = yield self.resources.preallocate(a=1)
        self._assert_allocated([3, 4])
        self._assert_preallocated({'a': 2, 'b': 0})

        modification3 = yield \
            self.resources.premodify(allocation_id=allocation.id, a=4)
        self.assertTrue(modification3 is None)
        self._assert_allocated([3, 4])
        self._assert_preallocated({'a': 2, 'b': 0})

    @defer.inlineCallbacks
    def testPremodifyNegativeDeltas(self):
        allocation = yield self.resources.allocate(a=3, b=2)
        allocation2 = yield self.resources.allocate(b=1)
        modification = yield \
            self.resources.premodify(allocation_id=allocation2.id, a=1, b=1)
        self._assert_allocated([4, 4])
        self._assert_preallocated({'a': 1, 'b': 1})
        # delta negative a=-1 doesn't match allocation2
        d = self.resources.premodify(allocation_id=allocation2.id, a=-1, b=1)
        self.assertFailure(d, resource.DeclarationError)
        yield d
        self._assert_allocated([4, 4])
        self._assert_preallocated({'a': 1, 'b': 1})

        self._assert_resource({'b': 1}, allocation2.id)
        yield self.resources.confirm(modification.id)
        self._assert_resource({'a': 1, 'b': 2}, allocation2.id)
        self._assert_resource({'a': 3, 'b': 2}, allocation.id)
        self._assert_allocated([4, 4])
        self._assert_preallocated({'a': 0, 'b': 0})

        # make a negative modification
        modification3 = yield \
                self.resources.premodify(allocation_id=allocation2.id, b=-1)
        yield self.resources.confirm(modification3.id)

        self._assert_allocated([4, 3])
        self._assert_preallocated({'a': 0, 'b': 0})

        modification4 = yield \
            self.resources.premodify(allocation_id=allocation.id, a=1, b=-1)
        self._assert_preallocated({'a': 1, 'b': 0})
        yield self.resources.confirm(modification4.id)
        self._assert_allocated([5, 2])
        self._assert_preallocated({'a': 0, 'b': 0})

    @defer.inlineCallbacks
    def testPremodifyTooMuchNegativeDeltas(self):
        allocation = yield self.resources.allocate(a=3, b=2)
        d = self.resources.premodify(allocation_id=allocation.id, b=-10)
        self.assertFailure(d, resource.DeclarationError)
        self._assert_allocated([3, 2])
        self._assert_preallocated({'a': 0, 'b': 0})

    @defer.inlineCallbacks
    def testPremodifyNonExistentChange(self):
        d = self.resources.confirm(100)
        self.assertFailure(d, resource.AllocationNotFound)
        yield d

    @defer.inlineCallbacks
    def testPremodifyTimeouts(self):
        allocation = yield self.resources.allocate(a=3, b=2)
        allocation2 = yield self.resources.allocate(b=1)
        modification = yield \
                self.resources.premodify(allocation_id=allocation.id, a=1, b=1)
        self._assert_preallocated({'a': 1, 'b': 1})
        # for timeout = 10
        self.agent.time += 15
        self._assert_preallocated({'a': 0, 'b': 0})

        d = self.resources.confirm(modification.id)
        self.assertFailure(d, resource.AllocationNotFound)
        yield d

    @defer.inlineCallbacks
    def testPremodifyTimeoutsMultipleModifications(self):
        allocation = yield self.resources.allocate(a=3, b=2)
        allocation2 = yield self.resources.allocate(b=1)
        modification = yield \
            self.resources.premodify(allocation_id=allocation.id, a=1, b=1)
        self._assert_allocated([4, 4])
        self._assert_preallocated({'a': 1, 'b': 1})

        self.agent.time += 5
        modification2 = yield \
            self.resources.premodify(allocation_id=allocation2.id, a=1)
        self._assert_allocated([5, 4])
        self._assert_preallocated({'a': 2, 'b': 1})

        yield self.resources.confirm(modification.id)
        self._assert_allocated([5, 4])
        self._assert_preallocated({'a': 1, 'b': 0})

        self.agent.time += 10
        self._assert_allocated([4, 4])
        self._assert_preallocated({'a': 0, 'b': 0})

        d = self.resources.confirm(modification2.id)
        self.assertFailure(d, resource.AllocationNotFound)
        yield d

    @defer.inlineCallbacks
    def testSerializationAllocation(self):
        allocation = yield self.resources.allocate(a=3, b=2)
        serialize = pytree.serialize
        unserialize = pytree.unserialize
        Ins = pytree.Instance
        self.assertEqual(allocation, unserialize(serialize(allocation)))

    @defer.inlineCallbacks
    def testGettingDeltas(self):
        alloc = yield self.resources.allocate(a=3, b=2)
        delta = yield self.resources.get_allocation_delta(alloc.id, a=5)
        self.assertEqual(dict(a=2, b=-2), delta)

        delta = yield self.resources.get_allocation_delta(alloc.id, a=3)
        self.assertEqual(dict(b=-2), delta)

        delta = yield self.resources.get_allocation_delta(alloc.id, a=3, b=4)
        self.assertEqual(dict(b=2), delta)
