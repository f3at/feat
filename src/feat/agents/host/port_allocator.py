from feat.common import log, serialization


@serialization.register
class PortAllocator(serialization.Serializable, log.Logger):
    """
    A list of ports that keeps track of which are available for use on a
    given machine.

    Copied from flumotion.common.worker.
    """

    def __init__(self, logger, ports):
        """
        @param ports: list of ports to pick from
        @type  ports: list of int
        """
        log.Logger.__init__(self, logger)

        self.ports = ports
        self.used = [0] * len(ports)

    def __eq__(self, other):
        if type(self) != type(other):
            return NotImplemented
        return self.ports == other.ports and \
            self.used == other.used

    def __ne__(self, other):
        return not self.__eq__(other)

    def restored(self):
        log.Logger.__init__(self, None)

    def reserve_ports(self, num_ports):
        """
        @param num_ports: number of ports to reserve
        @type  num_ports: int
        """
        ret = []
        while num_ports > 0:
            if not 0 in self.used:
                raise PortAllocationError('Could not allocate port')
            i = self.used.index(0)
            ret.append(self.ports[i])
            self.used[i] = 1
            num_ports -= 1
        return ret

    def set_ports_used(self, ports):
        """
        @param ports: list of ports to block
        @type  ports: list of int
        """
        for port in ports:
            try:
                i = self.ports.index(port)
            except ValueError:
                self.warning('Port set does not include port %d', port)
            else:
                if self.used[i]:
                    self.warning('port %d already in use!', port)
                else:
                    self.used[i] = 1

    def release_ports(self, ports):
        """
        @param ports: list of ports to release
        @type  ports: list of int
        """
        for p in ports:
            try:
                i = self.ports.index(p)
                if self.used[i]:
                    self.used[i] = 0
                else:
                    self.warning('releasing unallocated port: %d' % p)
            except ValueError:
                self.warning('releasing unknown port: %d' % p)

    def num_free(self):
        """
        Return the number of free ports.
        """
        return len(self.ports) - self.num_used()

    def num_used(self):
        """
        Return the number of used ports.
        """
        return len(filter(None, self.used))


class PortAllocationError(RuntimeError):
    pass
