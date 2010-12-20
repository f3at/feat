# -*- Mode: Python -*-
# vi:si:et:sw=4:sts=4:ts=4
import copy

from feat.common import log, enum
from feat.agencies.common import StateMachineMixin, ExpirationCallsMixin


class Resources(log.Logger, log.LogProxy):

    def __init__(self, agent):
        log.Logger.__init__(self, agent)
        log.LogProxy.__init__(self, agent)

        self.agent = agent

        self._totals = dict()
        self._allocations = list()

    def define(self, name, value):
        if not isinstance(value, int):
            raise DeclarationError('Resource value should be int, '
                                   'got %r instead.' % value.__class__)

        new_totals = copy.copy(self._totals)
        new_totals[name] = value
        self.validate(new_totals)
        self._totals = new_totals

    def validate(self, totals=None, allocations=None):
        totals, allocations = self._unpack_defaults(totals, allocations)

        allocated = self.allocated(totals, allocations)
        errors = list()
        for name in totals:
            if allocated[name] > totals[name]:
                errors.append('Not enough %r. Allocated already: %d. '
                              'New value: %d.' %\
                              (name, allocated[name], totals[name], ))
        if len(errors) > 0:
            raise NotEnoughResources(' '.join(errors))

    def allocated(self, totals=None, allocations=None):
        totals, allocations = self._unpack_defaults(totals, allocations)

        result = dict()
        for name in totals:
            result[name] = 0
        for allocation in allocations:
            for resource in allocation.resources:
                result[resource] += allocation.resources[resource]
        return result

    def append_allocation(self, allocation):
        if not isinstance(allocation, Allocation):
            raise ValueError('Expected Allocation class, got %r instead!' %\
                             allocation.__class__)
        self.validate(self._totals, self._allocations + [allocation])
        self._allocations.append(allocation)

    def remove_allocation(self, allocation):
        self._allocations.remove(allocation)

    def preallocate(self, expiration_time=None, **params):
        try:
            allocation = Allocation(self, expiration_time, **params)
            return allocation
        except NotEnoughResources:
            return None

    def allocate(self, **params):
        allocation = Allocation(self, expiration_time=None, **params)
        allocation.confirm()
        return allocation

    def get_time(self):
        '''
        Used by Allocation class to setup expiration call.
        '''
        return self.agent.medium.get_time()

    def _unpack_defaults(self, totals, allocations):
        if totals is None:
            totals = self._totals
        if allocations is None:
            allocations = self._allocations
        return totals, allocations


class AllocationState(enum.Enum):
    '''
    initiated    - not yet allocated
    preallocated - temporary allocation, will expire after the timeout
    allocated    - confirmed, will live until released
    expired      - preallocation has reached its timeout and has expired
    released     - release() was called
    '''

    (initiated, preallocated, allocated, expired, released) = range(5)


class Allocation(log.Logger, StateMachineMixin, ExpirationCallsMixin):

    default_timeout = 10

    def __init__(self, parent, expiration_time=None, **resources):
        log.Logger.__init__(self, parent)
        StateMachineMixin.__init__(self, AllocationState.initiated)
        ExpirationCallsMixin.__init__(self)

        self._parent = parent
        for name in resources:
            if name not in parent._totals:
                raise UnknownResource('Unknown resource name: %r.' % name)
            if not isinstance(resources[name], int):
                raise DeclarationError(
                    'Resource value should be int, got %r instead.' %\
                    resources[name].__class__)

        self.resources = resources
        self._parent.append_allocation(self)
        self._set_state(AllocationState.preallocated)

        if expiration_time is None:
            expiration_time = self._get_time() + self.default_timeout
        self._expire_at(expiration_time, self._timeout,
                        AllocationState.expired)

    def confirm(self):
        self._ensure_state(AllocationState.preallocated)
        self._cancel_expiration_call()
        self._set_state(AllocationState.allocated)

    def release(self):
        self._set_state(AllocationState.released)
        self._cancel_expiration_call()
        self._cleanup()

    def _timeout(self):
        self.info('Preallocation of %r has reached its timeout.',
                  self.resources)
        self._cleanup()

    def _cleanup(self):
        self._parent.remove_allocation(self)

    # Used by ExpirationCallsMixin

    def _get_time(self):
        return self._parent.get_time()

    def _error_handler(self, f):
        self.error(f)


class BaseResourceException(Exception):
    pass


class NotEnoughResources(BaseResourceException):
    pass


class UnknownResource(BaseResourceException):
    pass


class DeclarationError(BaseResourceException):
    pass
