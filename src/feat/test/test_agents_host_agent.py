from feat.agents.host import port_allocator
from feat.test.common import TestCase


class TestPortAllocator(TestCase):

    def setUp(self):
        TestCase.setUp(self)
        ports = (5000, 5010)
        self.allocator = port_allocator.PortAllocator(self, ports)

    def testAllocate(self):
        ports = self.allocator.reserve_ports(5)
        self.assertEqual(len(ports), 5)
        self.assertEqual(self.allocator.num_free(), 5)
        self.assertEqual(self.allocator.num_used(), 5)

    def testAllocateAndRelease(self):
        ports = self.allocator.reserve_ports(5)
        self.allocator.release_ports(ports[2:])
        self.assertEqual(self.allocator.num_free(), 8)

    def testAllocateTooManyPorts(self):
        self.assertRaises(port_allocator.PortAllocationError,
                          self.allocator.reserve_ports, 11)

    def testReleaseUnknownPort(self):
        self.allocator.release_ports([15000])
        self.assertEqual(self.allocator.num_free(), 10)

    def testReleaseUnallocatedPort(self):
        self.allocator.release_ports([5000])
        self.assertEqual(self.allocator.num_free(), 10)

    def testSetPortsUsed(self):
        self.allocator.set_ports_used([5000, 5001])
        self.assertEqual(self.allocator.num_used(), 2)

    def testSetPortAlreadyUsed(self):
        ports = self.allocator.reserve_ports(5)
        self.allocator.set_ports_used(ports)
        self.assertEqual(self.allocator.num_used(), 5)

    def testSetUnknownPort(self):
        self.allocator.set_ports_used([15000, 15001])
        self.assertEqual(self.allocator.num_used(), 0)
