from feat.common import log, serialization


@serialization.register
class PortAllocator(serialization.Serializable, log.Logger):
    """
    A list of ports that keeps track of which are available for use on a
    given machine.

    Copied from flumotion.common.worker.
    """

    DEFAULT_GROUP = 'misc'

    def __init__(self, logger, ports_groups):
        """
        @param ports_groups: range of ports to pick from, organized by groups
        @type  ports_groups: list of tuples with the group, first and last port
        """
        log.Logger.__init__(self, logger)
        self.set_ports_groups(ports_groups)


    def __eq__(self, other):
        if type(self) != type(other):
            return NotImplemented
        return self.ports_groups == other.ports_groups

    def __ne__(self, other):
        if type(self) != type(other):
            return NotImplemented
        return not self.__eq__(other)

    def restored(self):
        log.Logger.__init__(self, None)

    def set_ports_groups(self, ports_groups):
        # Dictionary with the group name as key and the a tuple with the range
        # start, range, stop and list of already allocated ports
        # {'misc': (2000, 3000, [2001, 2002, 2006]}
        self.ports_groups = {}
        for group, start, stop in ports_groups:
            self.ports_groups[group] = (start, stop, [])
        # Add the default group
        if self.DEFAULT_GROUP not in self.ports_groups:
            self.ports_groups[self.DEFAULT_GROUP]  = (0, 0, [])

    def reserve_ports(self, num_ports, group=DEFAULT_GROUP):
        """
        @param num_ports: number of ports to reserve
        @type  num_ports: int
        @param group: group of the allocated the ports (eg: 'streaming')
        @type  group: str
        """
        self.debug("Reserving %r from %r", num_ports, group)
        ret = []
        start, _, _ = self._get_group_status(group)
        bitmap = self._ports_to_bitmap(group)
        while num_ports > 0:
            if not False in bitmap:
                raise PortAllocationError(
                    'Could not allocate %r ports to group %r' % (num_ports, group))
            i = bitmap.index(False)
            ret.append(start + i)
            bitmap[i] = True
            num_ports -= 1
        self._update_ports(bitmap, group)
        return ret

    def set_ports_used(self, ports, group=DEFAULT_GROUP):
        """
        @param ports: list of ports to block
        @type  ports: list of int
        @param group: group of the allocated the ports (eg: 'streaming')
        @type  group: str
        """
        start, stop, _ = self._get_group_status(group)
        bitmap = self._ports_to_bitmap(group)
        for port in ports:
            if not start <= port <= stop:
                self.warning('Port set does not include port %d', port)
            else:
                i = port - start
                if bitmap[i]:
                    self.warning('port %d already in use!', port)
                else:
                    bitmap[i] = True
        self._update_ports(bitmap, group)

    def release_ports(self, ports, group=DEFAULT_GROUP):
        """
        @param ports: list of ports to release
        @type  ports: list of int
        @param group: group of the allocated the ports (eg: 'streaming')
        @type  group: str
        """
        self.debug("Releasing %r from %r", ports, group)
        start, stop, _ = self._get_group_status(group)
        bitmap = self._ports_to_bitmap(group)
        for p in ports:
            if start <= p <= stop:
                i = p - start
                if bitmap[i]:
                    bitmap[i] = False
                else:
                    self.warning('releasing unallocated port: %d' % p)
            else:
                self.warning('releasing unknown port: %d' % p)
        self._update_ports(bitmap, group)

    def num_free(self, group=DEFAULT_GROUP):
        """
        Return the number of free ports in a group

        @param group: group of the allocated the ports (eg: 'streaming')
        @type  group: str
        """
        start, stop, _ = self._get_group_status(group)
        return stop - start - self.num_used(group)

    def num_used(self, group=DEFAULT_GROUP):
        """
        Return the number of used ports in a group

        @param group: group of the allocated the ports (eg: 'streaming')
        @type  group: str
        """
        _, _, used = self._get_group_status(group)
        total = 0
        for r in used:
            total += r[1] - r[0] + 1
        return total

    def _ports_to_bitmap(self, group):
        """
        from [(5000, 5004), (5010, 5014)
        return [1, 1, 1, 1, 1, 0, 0, 0, 0, 0, 1, 1, 1, 1, 1]
        """
        start, stop, used = self._get_group_status(group)
        bitmap = [False] * (stop - start)
        for r in used:
            first = r[0] - start
            second = r[1] - start

            for i in range(first, second + 1):
                bitmap[i] = True
        return bitmap

    def _update_ports(self, bitmap, group):
        """
        from [1, 1, 1, 1, 1, 0, 0, 0, 0, 0, 1, 1, 1, 1, 1]
        update self.used to [(5000, 5004), (5010, 5014)]
        """
        used = []
        previous = 0
        index = 1
        start, stop, _ = self._get_group_status(group)
        while index < len(bitmap):
            if bitmap[index] == bitmap[index - 1]:
                index += 1
                continue
            if bitmap[previous]:
                used.append((start + previous,
                             start + index - 1))
            previous = index
            index += 1
        if bitmap[previous]:
            used.append((start + previous, start + index - 1))
        self.ports_groups[group] = (start, stop, used)
        self.used = used

    def _get_group_status(self, group):
        if group not in self.ports_groups:
            raise PortAllocationError("group %s not found in "
                                      "port allocator" % group)
        return self.ports_groups[group]


@serialization.register
class PortAllocationError(RuntimeError, serialization.Serializable):
    pass
