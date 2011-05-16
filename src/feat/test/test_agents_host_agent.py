from feat.agents.host import port_allocator
from feat.test.common import TestCase


class TestPortAllocator(TestCase):

    def setUp(self):
        TestCase.setUp(self)
        ports = [('default', 5000, 5010), ('streamer', 6000, 6010)]
        self.allocator = port_allocator.PortAllocator(self, ports)

    def testAllocateOne(self):
        ports = self.allocator.reserve_ports(1, 'default')
        self.assertEqual(len(ports), 1)
        self.assertEqual(self.allocator.num_free('default'), 9)
        self.assertEqual(self.allocator.num_used('default'), 1)

    def testAllocate(self):
        ports = self.allocator.reserve_ports(5, 'default')
        self.assertEqual(len(ports), 5)
        self.assertEqual(self.allocator.num_free('default'), 5)
        self.assertEqual(self.allocator.num_used('default'), 5)

    def testAllocateInGroups(self):
        ports = self.allocator.reserve_ports(5, 'default')
        self.assertEqual(len(ports), 5)
        ports = self.allocator.reserve_ports(3, 'streamer')
        self.assertEqual(len(ports), 3)
        self.assertEqual(self.allocator.num_free('default'), 5)
        self.assertEqual(self.allocator.num_used('default'), 5)
        self.assertEqual(self.allocator.num_free('streamer'), 7)
        self.assertEqual(self.allocator.num_used('streamer'), 3)

    def testAllocateAndRelease(self):
        ports = self.allocator.reserve_ports(5, 'default')
        self.allocator.release_ports(ports[2:], 'default')
        self.assertEqual(self.allocator.num_free('default'), 8)

    def testAllocateAndReleaseOne(self):
        ports = self.allocator.reserve_ports(1, 'default')
        self.allocator.release_ports(ports, 'default')
        self.assertEqual(self.allocator.num_free('default'), 10)

    def testAllocateAndReleaseInGroups(self):
        d_ports = self.allocator.reserve_ports(5, 'default')
        s_ports = self.allocator.reserve_ports(3, 'streamer')
        self.allocator.release_ports(d_ports[2:], 'default')
        self.allocator.release_ports(s_ports[:2], 'streamer')
        self.assertEqual(self.allocator.num_free('default'), 8)
        self.assertEqual(self.allocator.num_free('streamer'), 9)

    def testAllocateTooManyPorts(self):
        self.assertRaises(port_allocator.PortAllocationError,
                          self.allocator.reserve_ports, 'default', 11)

    def testReleaseUnknownPort(self):
        self.allocator.release_ports([15000], 'default')
        self.assertEqual(self.allocator.num_free('default'), 10)

    def testReleaseUnallocatedPort(self):
        self.allocator.release_ports([5000], 'default')
        self.assertEqual(self.allocator.num_free('default'), 10)

    def testSetPortsUsed(self):
        self.allocator.set_ports_used([5000, 5001], 'default')
        self.assertEqual(self.allocator.num_used('default'), 2)

    def testSetPortAlreadyUsed(self):
        ports = self.allocator.reserve_ports(5, 'default')
        self.allocator.set_ports_used(ports, 'default')
        self.assertEqual(self.allocator.num_used('default'), 5)

    def testSetGroup(self):
        self.allocator.set_ports_used([15000, 15001], 'default')
        self.assertEqual(self.allocator.num_used('default'), 0)

    def testSetUnknownGroup(self):
        self.failUnlessRaises(port_allocator.PortAllocationError,
                              self.allocator.set_ports_used,
                              [15000, 15001], 'manager')
