# -*- Mode: Python -*-
# vi:si:et:sw=4:sts=4:ts=4
from twisted.internet import defer
from zope.interface import implements

from feat.test import common
from feat.agents.base import resource, descriptor
from feat.common import delay
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
        preal = self._get_preallocated()
        self.assertEqual(expected, preal)

    def _assert_changes(self, expected):
        changes = self._get_changes()
        self.assertEqual(expected, changes)

    def _get_preallocated(self):
        totals = self.resources.get_totals()
        modifications = self.resources.get_modifications()
        result = dict()
        for name in totals:
            result[name] = 0
        for m in modifications:
            if isinstance(modifications[m], Allocation):
                for r in modifications[m].resources:
                    result[r] += modifications[m].resources[r]
        return result

    def _get_changes(self):
        totals = self.resources.get_totals()
        modifications = self.resources.get_modifications()
        result = dict()
        for name in totals:
            result[name] = 0
        for m in modifications:
            if isinstance(modifications[m], AllocationChange):
                for r in modifications[m].delta:
                    result[r] += max(0, modifications[m].delta[r])
        return result


@serialization.register
class DummyAgent(serialization.Serializable, common.DummyRecorderNode,
        common.Mock):

    type_name = "time-provider"

    implements(ITimeProvider)

    def __init__(self, test_case, allocations=None, current=None):
        self.time = current if current is not None else common.time()
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


class ResourcesTest(common.TestCase, Common):

    implements(journal.IRecorderNode)

    timeout = 1

    def setUp(self):
        delay.time_scale = 0.01

        self.allocations = dict()
        self.agent = DummyAgent(self, self.allocations)
        self.resources = resource.Resources(self.agent)

        self.resources.define('a', 5)
        self.resources.define('b', 6)

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
        self._assert_changes({'a': 0, 'b': 0})
        self.assertCalled(self.agent, 'update_descriptor', times=0)
        yield self.resources.release(allocation.id)
        self._assert_allocated([0, 0])
        self._assert_preallocated({'a': 0, 'b': 0})
        self._assert_changes({'a': 0, 'b': 0})
        self.assertCalled(self.agent, 'update_descriptor', times=0)

    @defer.inlineCallbacks
    def testCannotOverallocate(self):
        allocation = yield self.resources.preallocate(a=10)
        self.assertTrue(allocation is None)
        self._assert_allocated([0, 0])
        self.assertCalled(self.agent, 'update_descriptor', times=0)

    @defer.inlineCallbacks
    def testAllocateThrowsOnOverflow(self):
        yield self.assertFails(resource.NotEnoughResources,
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
        self._assert_changes({'a': 0, 'b': 0})
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
        self._assert_changes({'a': 0, 'b': 0})

    @defer.inlineCallbacks
    def testPrallocateAlocateModify(self):
        allocation1 = yield self.resources.allocate(a=1)
        allocation2 = yield self.resources.preallocate(b=1)
        allocation3 = yield self.resources.preallocate(a=1)
        allocation4 = yield self.resources.allocate(b=1)
        modification = yield \
            self.resources.premodify(allocation_id=allocation1.id, a=1, b=1)
        self._assert_allocated([3, 3])
        self._assert_preallocated({'a': 1, 'b': 1})
        self._assert_changes({'a': 1, 'b': 1})

    def testBadDefine(self):
        return self.assertAsyncFailure(None, resource.DeclarationError,
                                       self.resources.define, 'c', 'not int')

    @defer.inlineCallbacks
    def testAllocationExists(self):
        allocation = yield self.resources.allocate(a=3)
        a = yield fiber.maybe_fiber(self.resources.get_allocation,
                allocation.id)
        self.assertIsInstance(a, resource.Allocation)

    @defer.inlineCallbacks
    def testAllocationDoesNotExist(self):
        allocation = yield self.resources.allocate(a=3)
        d = defer.succeed(None)
        d = self.assertAsyncFailure(d, (resource.AllocationNotFound, ),
                fiber.maybe_fiber, self.resources.get_allocation, 2)
        yield d

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
        self._assert_preallocated({'a': 0, 'b': 0})
        self._assert_changes({'a': 1, 'b': 1})

    @defer.inlineCallbacks
    def testApplyModificationSuccess(self):
        allocation = yield self.resources.allocate(a=3, b=2)
        self.assertCalled(self.agent, 'update_descriptor', times=1)
        allocation2 = yield self.resources.allocate(b=1)
        self.assertCalled(self.agent, 'update_descriptor', times=2)
        modification = yield \
            self.resources.premodify(allocation_id=allocation.id, a=1, b=1)
        # apply modification
        self.assertCalled(self.agent, 'update_descriptor', times=2)
        yield self.resources.apply_modification(modification.id)
        self.assertCalled(self.agent, 'update_descriptor', times=3)

        self._assert_allocated([4, 4])
        self._assert_preallocated({'a': 0, 'b': 0})
        self._assert_changes({'a': 0, 'b': 0})
        self.assertEqual({'a': 4, 'b': 3},
                self.resources.get_allocations()[allocation.id].resources)
        self.assertEqual(0, len(self.resources.get_modifications()))

    @defer.inlineCallbacks
    def testPremodifyMultipleModifications(self):
        allocation = yield self.resources.allocate(a=3, b=2)
        allocation2 = yield self.resources.allocate(b=1)
        modification = yield \
            self.resources.premodify(allocation_id=allocation.id, a=1, b=1)
        yield self.resources.apply_modification(modification.id)
        # premodify again
        modification2 = yield \
                self.resources.premodify(allocation_id=allocation2.id, a=1)
        self._assert_allocated([5, 4])
        self._assert_preallocated({'a': 0, 'b': 0})
        self._assert_changes({'a': 1, 'b': 0})
        self.assertEqual(1, len(self.resources.get_modifications()))

    @defer.inlineCallbacks
    def testPremodifyOverallocate(self):
        allocation = yield self.resources.allocate(a=3, b=2)
        allocation2 = yield self.resources.allocate(b=1)
        modification = yield \
            self.resources.premodify(allocation_id=allocation.id, a=1, b=1)
        modification2 = yield \
                self.resources.premodify(allocation_id=allocation2.id, a=1)
        self._assert_allocated([5, 4])
        self._assert_preallocated({'a': 0, 'b': 0})
        self._assert_changes({'a': 2, 'b': 1})
        yield self.resources.apply_modification(modification.id)

        modification3 = yield \
            self.resources.premodify(allocation_id=allocation.id, a=2)
        self.assertTrue(modification3 is None)

        self._assert_allocated([5, 4])
        self._assert_preallocated({'a': 0, 'b': 0})
        self._assert_changes({'a': 1, 'b': 0})
        self.assertEqual(1, len(self.resources.get_modifications()))

    @defer.inlineCallbacks
    def testPremodifyOverallocate2(self):
        allocation = yield self.resources.allocate(b=2)
        allocation2 = yield self.resources.allocate(b=1)
        modification = yield \
            self.resources.premodify(allocation_id=allocation.id, a=1, b=1)
        yield self.resources.apply_modification(modification.id)
        modification2 = yield \
                self.resources.premodify(allocation_id=allocation2.id, a=1)
        preallocation = yield self.resources.preallocate(a=1)
        self._assert_allocated([3, 4])
        self._assert_preallocated({'a': 1, 'b': 0})
        self._assert_changes({'a': 1, 'b': 0})
        # a 5 b 4
        modification3 = yield \
            self.resources.premodify(allocation_id=allocation.id, a=4)
        self.assertTrue(modification3 is None)

        self._assert_allocated([3, 4])
        self._assert_preallocated({'a': 1, 'b': 0})
        self._assert_changes({'a': 1, 'b': 0})
        self.assertEqual(2, len(self.resources.get_modifications()))

    @defer.inlineCallbacks
    def testPremodifyNegativeDeltas(self):
        allocation = yield self.resources.allocate(a=3, b=2)
        allocation2 = yield self.resources.allocate(b=1)
        modification = yield \
            self.resources.premodify(allocation_id=allocation2.id, a=1, b=1)
        self._assert_allocated([4, 4])
        self._assert_preallocated({'a': 0, 'b': 0})
        self._assert_changes({'a': 1, 'b': 1})
        self.assertEqual(1, len(self.resources.get_modifications()))
        # delta negative
        modification2 = yield \
            self.resources.premodify(allocation_id=allocation2.id, a=-1, b=1)
        # here a=-1 must be ignored
        self._assert_allocated([4, 5])
        self._assert_preallocated({'a': 0, 'b': 0})
        self._assert_changes({'a': 1, 'b': 2})
        self.assertEqual(2, len(self.resources.get_modifications()))

        self.assertEqual({'b': 1},
                self.resources.get_allocations()[allocation2.id].resources)
        # apply the previous change
        yield self.resources.apply_modification(modification2.id)
        # modify allocation 2: {b:1} with c3 -> 2:{a:-1,b:1},
        # so -1 should be avoided and 'a' set to 0
        self.assertEqual({'a': 0, 'b': 2},
                self.resources.get_allocations()[allocation2.id].resources)
        self._assert_allocated([4, 5])
        self._assert_preallocated({'a': 0, 'b': 0})
        self._assert_changes({'a': 1, 'b': 1})
        self.assertEqual(1, len(self.resources.get_modifications()))

        # make a negative modification
        modification3 = yield \
                self.resources.premodify(allocation_id=allocation2.id, b=-1)
        yield self.resources.apply_modification(modification3.id)

        # self.assertEqual({'b':-1},

        self._assert_allocated([4, 4])
        self._assert_preallocated({'a': 0, 'b': 0})
        self._assert_changes({'a': 1, 'b': 1})
        self.assertEqual(1, len(self.resources.get_modifications()))

        modification4 = yield \
            self.resources.premodify(allocation_id=allocation.id, a=1, b=-1)
        yield self.resources.apply_modification(modification4.id)
        self._assert_allocated([5, 3])
        self._assert_preallocated({'a': 0, 'b': 0})
        self._assert_changes({'a': 1, 'b': 1})

    @defer.inlineCallbacks
    def testPremodifyTooMuchNegativeDeltas(self):
        allocation = yield self.resources.allocate(a=3, b=2)
        modification = yield \
                self.resources.premodify(allocation_id=allocation.id, b=-10)
        yield self.resources.apply_modification(modification.id)
        self._assert_allocated([3, 0])
        self._assert_preallocated({'a': 0, 'b': 0})
        self._assert_changes({'a': 0, 'b': 0})

    @defer.inlineCallbacks
    def testPremodifyTooMuchNegativeDeltasIgnored(self):
        allocation = yield self.resources.allocate(a=3, b=2)

        modification = yield \
            self.resources.premodify(allocation_id=allocation.id, a=1, b=-10)
        yield self.resources.apply_modification(modification.id)
        self._assert_allocated([4, 0])
        self._assert_preallocated({'a': 0, 'b': 0})
        self._assert_changes({'a': 0, 'b': 0})

    @defer.inlineCallbacks
    def testPremodifyNonExistentChange(self):
        allocation = yield self.resources.allocate(a=3, b=2)
        allocation2 = yield self.resources.allocate(b=1)
        modification = yield \
                self.resources.premodify(allocation_id=allocation.id, a=1, b=1)

        # try to apply a change that does not exist
        d = defer.succeed(None)
        d = self.assertAsyncFailure(d, (resource.AllocationChangeNotFound, ),
                fiber.maybe_fiber, self.resources.apply_modification, 100)
        yield d

    @defer.inlineCallbacks
    def testPremodifyTimeouts(self):
        allocation = yield self.resources.allocate(a=3, b=2)
        allocation2 = yield self.resources.allocate(b=1)
        modification = yield \
                self.resources.premodify(allocation_id=allocation.id, a=1, b=1)
        self.assertEqual(1, len(self.resources.get_modifications()))
        # for timeout = 10
        self.agent.time += 15
        self.assertEqual(0, len(self.resources.get_modifications()))

        d = defer.succeed(None)
        d = self.assertAsyncFailure(d, (resource.AllocationChangeNotFound, ),
                fiber.maybe_fiber, self.resources.apply_modification,
                modification.id)
        yield d

    @defer.inlineCallbacks
    def testPremodifyTimeoutsMultipleModifications(self):
        allocation = yield self.resources.allocate(a=3, b=2)
        allocation2 = yield self.resources.allocate(b=1)
        modification = yield \
            self.resources.premodify(allocation_id=allocation.id, a=1, b=1)
        self._assert_allocated([4, 4])
        self._assert_preallocated({'a': 0, 'b': 0})
        self._assert_changes({'a': 1, 'b': 1})

        self.agent.time += 5
        modification2 = yield \
            self.resources.premodify(allocation_id=allocation2.id, a=1)
        self._assert_allocated([5, 4])
        self._assert_preallocated({'a': 0, 'b': 0})
        self._assert_changes({'a': 2, 'b': 1})

        yield self.resources.apply_modification(modification.id)
        self._assert_allocated([5, 4])
        self._assert_preallocated({'a': 0, 'b': 0})
        self._assert_changes({'a': 1, 'b': 0})

        self.agent.time += 10
        self.assertEqual({'a': 4, 'b': 4}, self.resources.allocated())
        self._assert_allocated([4, 4])
        self._assert_preallocated({'a': 0, 'b': 0})
        self._assert_changes({'a': 0, 'b': 0})

        d = defer.succeed(None)
        d = self.assertAsyncFailure(d, (resource.AllocationChangeNotFound, ),
                fiber.maybe_fiber, self.resources.apply_modification,
                modification2.id)
        yield d

    @defer.inlineCallbacks
    def testSerializationAllocation(self):
        allocation = yield self.resources.allocate(a=3, b=2)
        serialize = pytree.serialize
        unserialize = pytree.unserialize
        Ins = pytree.Instance
        self.assertEqual(allocation, unserialize(serialize(allocation)))

    @defer.inlineCallbacks
    def testSerializationAllocationChange(self):
        allocation = yield self.resources.allocate(a=3, b=2)
        modification = yield \
                self.resources.premodify(allocation_id=allocation.id, a=1, b=1)
        serialize = pytree.serialize
        unserialize = pytree.unserialize
        Ins = pytree.Instance
        modifications = self.resources.get_modifications()[modification.id]
        self.assertEqual(modification, unserialize(serialize(modification)))
