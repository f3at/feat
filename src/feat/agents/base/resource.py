# -*- Mode: Python -*-
# vi:si:et:sw=4:sts=4:ts=4
import copy

from feat.common import log, enum, serialization, error_handler, delay, fiber
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

    # Public API

    @replay.mutable
    def load(self, state, allocations):
        '''
        Loads the list of allocations. Meant to be used during agent
        initialization for restoring allocations stored in descriptor.
        '''
        assert isinstance(allocations, list)
        for allocation in allocations:
            assert allocation.state == AllocationState.allocated
            for name in allocation.resources:
                try:
                    self._check_resource_exists(name)
                except UnknownResource:
                    self.define(name, 0)
            self._append_allocation(allocation, force=True)

    @replay.immutable
    def get_totals(self, state):
        return copy.copy(state.totals)

    @replay.mutable
    def preallocate(self, state, **params):
        try:
            self._validate_params(params)
            allocation = Allocation(**params)
            allocation._set_state(AllocationState.preallocated)
            self._append_allocation(allocation)
            self._setup_allocation_expiration(allocation)
            return allocation
        except NotEnoughResources:
            return None

    @replay.mutable
    def confirm(self, state, allocation):
        allocation.confirm()
        f = fiber.Fiber()
        f.add_callback(self._append_allocation_to_descriptor)
        return f.succeed(allocation)

    @replay.mutable
    def allocate(self, state, **params):
        self._validate_params(params)
        allocation = Allocation(**params)
        self._append_allocation(allocation)
        allocation._set_state(AllocationState.allocated)
        f = fiber.Fiber()
        f.add_callback(self._append_allocation_to_descriptor)
        return f.succeed(allocation)

    @replay.mutable
    def release(self, state, allocation):
        assert allocation in state.allocations
        was_allocated = allocation._cmp_state(AllocationState.allocated)
        allocation.release()
        self._remove_allocation(allocation)
        if was_allocated:
            f = fiber.Fiber()
            f.add_callback(self._remove_allocation_from_descriptor)
            return f.succeed(allocation)

    @replay.mutable
    def define(self, state, name, value):
        if not isinstance(value, int):
            raise DeclarationError('Resource value should be int, '
                                   'got %r instead.' % value.__class__)

        new_totals = copy.copy(state.totals)
        is_decreasing = name in new_totals and new_totals[name] > value
        new_totals[name] = value
        if is_decreasing:
            self._validate(new_totals)
        state.totals = new_totals

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

    # ENDOF Public API

    # handling allocation list in descriptor

    @replay.journaled
    def _append_allocation_to_descriptor(self, state, allocation):

        def do_append(desc, allocation):
            desc.allocations.append(allocation)
            return allocation

        f = fiber.Fiber()
        f.add_callback(state.agent.update_descriptor, allocation)
        return f.succeed(do_append)

    @replay.journaled
    def _remove_allocation_from_descriptor(self, state, allocation):

        def do_remove(desc, allocation):
            if allocation not in desc.allocations:
                self.warning('Tried to remove allocation %r from descriptor, '
                             'but the allocation are: %r',
                             allocation, desc.allocations)
                return

            desc.allocations.remove(allocation)
            return allocation

        f = fiber.Fiber()
        f.add_callback(state.agent.update_descriptor, allocation)
        return f.succeed(do_remove)

    # Methods for maintaining the allocations inside

    def _validate(self, totals=None, allocations=None):
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

    @replay.mutable
    def _append_allocation(self, state, allocation, force=False):
        if not isinstance(allocation, Allocation):
            raise ValueError('Expected Allocation class, got %r instead!' %\
                             allocation.__class__)
        if not force:
            self._validate(state.totals, state.allocations + [allocation])
        state.allocations.append(allocation)

    @replay.side_effect
    def _setup_allocation_expiration(self, allocation):
        allocation.expire_in(allocation.default_timeout,
                             self._expire_allocation)

    @replay.mutable
    def _expire_allocation(self, state, allocation):
        allocation._set_state(AllocationState.expired)
        self._remove_allocation(allocation)

    @replay.mutable
    def _remove_allocation(self, state, allocation):
        state.allocations.remove(allocation)

    def _validate_params(self, params):
        """
        Check that params is a dictionary with keys of the resources we
        already know about and integer values.
        """
        for name in params:
            self._check_resource_exists(name)
            if not isinstance(params[name], int):
                raise DeclarationError(
                    'Resource value should be int, got %r instead.' %\
                    params[name].__class__)

    @replay.immutable
    def _unpack_defaults(self, state, totals, allocations):
        if totals is None:
            totals = state.totals
        if allocations is None:
            allocations = state.allocations
        return totals, allocations

    @replay.immutable
    def _check_resource_exists(self, state, name):
        if name not in state.totals:
            raise UnknownResource('Unknown resource name: %r.' % name)

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
class Allocation(StateMachineMixin, serialization.Serializable):

    type_name = 'alloc'

    default_timeout = 10
    _error_handler=error_handler

    def __init__(self, allocated=False, **resources):
        init_state = allocated and AllocationState.allocated or \
                     AllocationState.initiated
        StateMachineMixin.__init__(self, init_state)

        self._expiration_call = None

        self.resources = resources

    @replay.side_effect
    def expire_in(self, time_left, cb):
        self._expiration_call = delay.callLater(time_left, cb, self)

    @replay.side_effect
    def cancel_expiration_call(self):
        if self._expiration_call and not (self._expiration_call.called or\
                                          self._expiration_call.cancelled):
            self._expiration_call.cancel()
            self._expiration_call = None

    def confirm(self):
        self._ensure_state(AllocationState.preallocated)
        self.cancel_expiration_call()
        self._set_state(AllocationState.allocated)
        return self

    def release(self):
        self._set_state(AllocationState.released)
        self.cancel_expiration_call()

    def _get_time(self):
        return self._parent.get_time()

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
