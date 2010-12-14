# -*- Mode: Python -*-
# vi:si:et:sw=4:sts=4:ts=4
import time

from twisted.internet import defer

from feat.test import common
from feat.agents.base import resource
from feat.common import delay


class ResourcesTest(common.TestCase):

    timeout = 1

    def setUp(self):
        delay.time_scale = 0.01

        self.resources = resource.Resources(self)
        setattr(self.resources, 'get_time', self._get_time)

        self.resources.define('a', 5)
        self.resources.define('b', 6)

    def testCheckingEmptyAllocations(self):
        al = self.resources.allocated()
        self.assertEqual(['a', 'b'], al.keys())
        self.assertEqual([0, 0], al.values())

    @defer.inlineCallbacks
    def testPreallocationExpires(self):
        allocation = self.resources.preallocate(a=3, b=4)
        self.assertIsInstance(allocation, resource.Allocation)
        self._assert_allocated([3, 4])

        d = self.cb_after(None, self.resources, 'remove_allocation')
        yield d
        self._assert_allocated([0, 0])
        self.assertEqual(resource.AllocationState.expired, allocation.state)

    def testCannotOverallocate(self):
        allocation = self.resources.preallocate(a=10)
        self.assertTrue(allocation is None)
        self._assert_allocated([0, 0])

    def testAllocateThrowsOnOverflow(self):
        self.assertRaises(resource.NotEnoughResources,
                          self.resources.allocate, a=10)

    def testIncorrectAllocation(self):
        self.assertRaises(resource.DeclarationError,
                          self.resources.allocate, a='sth stupupid')
        self.assertRaises(resource.DeclarationError,
                          self.resources.preallocate, a='sth stupupid')
        self.assertRaises(resource.UnknownResource,
                          self.resources.allocate, unknown=4)
        self.assertRaises(resource.UnknownResource,
                          self.resources.preallocate, unknown=4)

    def testGettingRealAllocation(self):
        allocation = self.resources.allocate(a=3)
        self.assertEqual(resource.AllocationState.allocated, allocation.state)
        self._assert_allocated([3, 0])

        allocation.release()
        self._assert_allocated([0, 0])
        self.assertEqual(resource.AllocationState.released, allocation.state)

    def testBadDefine(self):
        self.assertRaises(resource.DeclarationError, self.resources.define,
                          'c', 'not int')

    def _assert_allocated(self, expected):
        al = self.resources.allocated()
        self.assertEqual(expected, al.values())

    def _get_time(self):
        return time.time()
