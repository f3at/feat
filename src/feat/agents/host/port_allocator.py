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
        @param ports: range of ports to pick from
        @type  ports: tuple of two elements (first and last port)
        """
        log.Logger.__init__(self, logger)

        self.ports = ports

        # list of tuples representing ranges of used ports
        # for instance:
        # [(5000, 5004), (5005, 5010), (5015, 5020)]
        self.used = []

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
        bitmap = self._ports_to_bitmap()
        while num_ports > 0:
            if not False in bitmap:
                raise PortAllocationError('Could not allocate port')
            i = bitmap.index(False)
            ret.append(self.ports[0] + i)
            bitmap[i] = True
            num_ports -= 1
        self._update_ports(bitmap)
        return ret

    def set_ports_used(self, ports):
        """
        @param ports: list of ports to block
        @type  ports: list of int
        """
        bitmap = self._ports_to_bitmap()
        for port in ports:
            if not self.ports[0] <= port <= self.ports[1]:
                self.warning('Port set does not include port %d', port)
            else:
                i = port - self.ports[0]
                if bitmap[i]:
                    self.warning('port %d already in use!', port)
                else:
                    bitmap[i] = True
        self._update_ports(bitmap)

    def release_ports(self, ports):
        """
        @param ports: list of ports to release
        @type  ports: list of int
        """
        bitmap = self._ports_to_bitmap()
        for p in ports:
            if self.ports[0] <= p <= self.ports[1]:
                i = p - self.ports[0]
                if bitmap[i]:
                    bitmap[i] = False
                else:
                    self.warning('releasing unallocated port: %d' % p)
            else:
                self.warning('releasing unknown port: %d' % p)
        self._update_ports(bitmap)

    def num_free(self):
        """
        Return the number of free ports.
        """
        return self.ports[1] - self.ports[0] - self.num_used()

    def num_used(self):
        """
        Return the number of used ports.
        """
        total = 0
        for r in self.used:
            total += r[1] - r[0] + 1
        return total

    def _ports_to_bitmap(self):
        """
        from [(5000, 5004), (5010, 5014)
        return [1, 1, 1, 1, 1, 0, 0, 0, 0, 0, 1, 1, 1, 1, 1]
        """
        bitmap = [False] * (self.ports[1] - self.ports[0])
        for r in self.used:
            first = r[0] - self.ports[0]
            second = r[1] - self.ports[0]
            for i in range(first, second + 1):
                bitmap[i] = True
        return bitmap

    def _update_ports(self, bitmap):
        """
        from [1, 1, 1, 1, 1, 0, 0, 0, 0, 0, 1, 1, 1, 1, 1]
        update self.used to [(5000, 5004), (5010, 5014)]
        """
        used = []
        previous = 0
        index = 1
        while index < len(bitmap):
            if bitmap[index] == bitmap[index - 1]:
                index += 1
                continue
            if bitmap[previous]:
                used.append((self.ports[0] + previous,
                             self.ports[0] + index - 1))
            previous = index
            index += 1
        if bitmap[previous]:
            used.append((self.ports[0] + previous, self.ports[0] + index - 1))
        self.used = used


@serialization.register
class PortAllocationError(RuntimeError, serialization.Serializable):
    pass
