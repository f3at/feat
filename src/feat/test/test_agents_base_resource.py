# -*- Mode: Python -*-
# vi:si:et:sw=4:sts=4:ts=4
import time

from twisted.internet import defer
from zope.interface import implements

from feat.test import common
from feat.agents.base import resource
from feat.common import delay
from feat.interface import journal


class DummyAgent(common.DummyRecordNode, common.Mock):

    def __init__(self, test_case):
        common.DummyRecordNode.__init__(self, test_case)
        common.Mock.__init__(self)

    @common.Mock.record
    def update_descriptor(self, method, allocation):
        assert callable(method)
        assert isinstance(allocation, resource.Allocation)
        return defer.succeed(allocation)


class ResourcesTest(common.TestCase):

    implements(journal.IRecorderNode)

    timeout = 1

    def setUp(self):

        delay.time_scale = 0.01

        self.agent = DummyAgent(self)
        self.resources = resource.Resources(self.agent)
        setattr(self.resources, 'get_time', self._get_time)

        self.resources.define('a', 5)
        self.resources.define('b', 6)

    def testCheckingEmptyAllocations(self):
        al = self.resources.allocated()
        self.assertEqual(['a', 'b'], al.keys())
        self.assertEqual([0, 0], al.values())

    @defer.inlineCallbacks
    def testPreallocationExpires(self):
        d = self.cb_after(None, self.resources, '_remove_allocation')

        allocation = yield self.resources.preallocate(a=3, b=4)
        self.assertIsInstance(allocation, resource.Allocation)
        self._assert_allocated([3, 4])

        yield d

        self._assert_allocated([0, 0])
        self.assertEqual(resource.AllocationState.expired,
                         allocation.state)

    @defer.inlineCallbacks
    def testCannotOverallocate(self):
        allocation = yield self.resources.preallocate(a=10)
        self.assertTrue(allocation is None)
        self._assert_allocated([0, 0])
        self.assertCalled(self.agent, 'update_descriptor', times=0)

    def testAllocateThrowsOnOverflow(self):
        self.assertRaises(resource.NotEnoughResources,
                          self.resources.allocate, a=10)
        self.assertCalled(self.agent, 'update_descriptor', times=0)

    def testIncorrectAllocation(self):
        self.assertRaises(resource.DeclarationError,
                          self.resources.allocate, a='sth stupupid')
        self.assertRaises(resource.DeclarationError,
                          self.resources.preallocate, a='sth stupupid')
        self.assertRaises(resource.UnknownResource,
                          self.resources.allocate, unknown=4)
        self.assertRaises(resource.UnknownResource,
                          self.resources.preallocate, unknown=4)
        self.assertCalled(self.agent, 'update_descriptor', times=0)

    @defer.inlineCallbacks
    def testGettingRealAllocation(self):
        allocation = yield self.resources.allocate(a=3)
        self.assertEqual(resource.AllocationState.allocated,
                         allocation.state)
        self._assert_allocated([3, 0])

        self.assertCalled(self.agent, 'update_descriptor')

        yield self.resources.release(allocation)

        self.assertCalled(self.agent, 'update_descriptor', times=2)

        self._assert_allocated([0, 0])
        self.assertEqual(resource.AllocationState.released,
                         allocation.state)

    @defer.inlineCallbacks
    def testPreallocatingAndConfirming(self):
        allocation = yield self.resources.preallocate(a=3)
        self.assertEqual(resource.AllocationState.preallocated,
                         allocation.state)
        self._assert_allocated([3, 0])
        self.assertCalled(self.agent, 'update_descriptor', times=0)

        yield self.resources.confirm(allocation)
        self.assertCalled(self.agent, 'update_descriptor', times=1)

    def testBadDefine(self):
        self.assertRaises(resource.DeclarationError, self.resources.define,
                          'c', 'not int')

    def _assert_allocated(self, expected):
        al = self.resources.allocated()
        self.assertEqual(expected, al.values())

    def _get_time(self):
        return time.time()
