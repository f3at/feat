# -*- Mode: Python -*-
# vi:si:et:sw=4:sts=4:ts=4
import copy

from feat.common import log, enum, serialization, error_handler
from feat.agents.base import replay
from feat.agencies.common import StateMachineMixin, ExpirationCallsMixin


@serialization.register
class Resources(log.Logger, log.LogProxy, replay.Replayable):

    def __init__(self, agent):
        log.Logger.__init__(self, agent)
        log.LogProxy.__init__(self, agent)
        replay.Replayable.__init__(self, agent)

    def init_state(self, state, agent):
        state.agent = agent
        state.totals = dict()
        state.allocations = list()

    @replay.immutable
    def restored(self, state):
        log.Logger.__init__(self, state.agent)
        log.LogProxy.__init__(self, state.agent)
        replay.Replayable.restored(self)

    @replay.mutable
    def define(self, state, name, value):
        if not isinstance(value, int):
            raise DeclarationError('Resource value should be int, '
                                   'got %r instead.' % value.__class__)

        new_totals = copy.copy(state.totals)
        new_totals[name] = value
        self.validate(new_totals)
        state.totals = new_totals

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
            ar = allocation.resources
            for resource in ar:
                result[resource] += ar[resource]
        return result

    @replay.journaled
    def set_allocation_state(self, state, allocation, m_state):
        # we consider state of allocation part a state of the resources object
        # for this reason they need to be changed by the journaled method
        StateMachineMixin._set_state(allocation, m_state)

    @replay.immutable
    def get_totals(self, state):
        return copy.copy(state.totals)

    @replay.mutable
    def append_allocation(self, state, allocation):
        if not isinstance(allocation, Allocation):
            raise ValueError('Expected Allocation class, got %r instead!' %\
                             allocation.__class__)
        self.validate(state.totals, state.allocations + [allocation])
        state.allocations.append(allocation)

    @replay.mutable
    def remove_allocation(self, state, allocation):
        state.allocations.remove(allocation)

    @replay.journaled
    def preallocate(self, state, **params):
        try:
            allocation = Allocation(self, **params)
            return allocation
        except NotEnoughResources:
            return None

    @replay.journaled
    def allocate(self, state, **params):
        allocation = Allocation(self, **params)
        allocation.confirm()
        return allocation

    @replay.journaled
    def release(self, state, allocation):
        assert allocation in state.allocations
        allocation.release()

    @replay.immutable
    def _unpack_defaults(self, state, totals, allocations):
        if totals is None:
            totals = state.totals
        if allocations is None:
            allocations = state.allocations
        return totals, allocations

    @replay.immutable
    def check_name_exists(self, state, name):
        if name not in state.totals:
            raise UnknownResource('Unknown resource name: %r.' % name)

    @replay.immutable
    def get_time(self, state):
        return state.agent.get_time()

    @replay.immutable
    def __repr__(self, state):
        return "<Resources. Totals: %r, Allocations: %r>" %\
               (state.totals, state.allocations)

    @replay.immutable
    def __eq__(self, state, other):
        if not isinstance(other, type(self)):
            return NotImplemented
        os = other._get_state()
        if os.totals != state.totals:
            return False
        if state.allocations != os.allocations:
            return False
        return True

    def __ne__(self, other):
        return not self.__eq__(other)


class AllocationState(enum.Enum):
    '''
    initiated    - not yet allocated
    preallocated - temporary allocation, will expire after the timeout
    allocated    - confirmed, will live until released
    expired      - preallocation has reached its timeout and has expired
    released     - release() was called
    '''

    (initiated, preallocated, allocated, expired, released) = range(5)


@serialization.register
class Allocation(log.Logger, ExpirationCallsMixin, StateMachineMixin,
                 serialization.Serializable):

    default_timeout = 10
    _error_handler=error_handler

    def __init__(self, parent, **resources):
        log.Logger.__init__(self, parent)
        ExpirationCallsMixin.__init__(self)
        StateMachineMixin.__init__(self, AllocationState.initiated)

        self._expiration_call = None

        for name in resources:
            parent.check_name_exists(name)
            if not isinstance(resources[name], int):
                raise DeclarationError(
                    'Resource value should be int, got %r instead.' %\
                    resources[name].__class__)

        self._parent = parent

        self.resources = resources
        self._parent.append_allocation(self)
        self._set_state(AllocationState.preallocated)

        self._initiate()

    def restored(self):
        # unless the Allocation is binded to Resource object it cannot log
        # lines
        log.Logger.__init__(self, None)

    @replay.side_effect
    def _initiate(self):
        expiration_time = self.default_timeout + self._get_time()
        self._setup_expiration_call(expiration_time, self._on_timeout)

    # public API

    def confirm(self):
        self._ensure_state(AllocationState.preallocated)
        self._cancel_expiration_call()
        self._set_state(AllocationState.allocated)

    def release(self):
        self._set_state(AllocationState.released)
        self._cancel_expiration_call()
        self._cleanup()

    # private section

    def _get_time(self):
        return self._parent.get_time()

    def _set_state(self, state):
        self._parent.set_allocation_state(self, state)

    def _on_timeout(self):
        self.info('Preallocation of %r has reached its timeout.', self)
        self._set_state(AllocationState.expired)
        self._cleanup()

    def _cleanup(self):
        self._parent.remove_allocation(self)

    def __repr__(self):
        return "<Allocation state: %r, Resource: %r>" %\
               (self.state.name, self.resources, )

    def __eq__(self, other):
        if not isinstance(other, type(self)):
            return NotImplemented
        return self.state == other.state and self.resources == other.resources

    def __ne__(self, other):
        return not self.__eq__(other)


class BaseResourceException(Exception):
    pass


class NotEnoughResources(BaseResourceException):
    pass


class UnknownResource(BaseResourceException):
    pass


class DeclarationError(BaseResourceException):
    pass
