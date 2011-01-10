# -*- Mode: Python -*-
# vi:si:et:sw=4:sts=4:ts=4
import copy

from feat.common import log, enum, delay, fiber, serialization
from feat.agents.base import replay


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
            ar = allocation.get_resources()
            for resource in ar:
                result[resource] += ar[resource]
        return result

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
            allocation.initiate()
            return allocation
        except NotEnoughResources:
            return None

    @replay.journaled
    def allocate(self, state, **params):
        allocation = Allocation(self, **params)
        allocation.initiate()
        allocation.confirm()
        return allocation

    @replay.immutable
    def get_time(self, state):
        '''
        Used by Allocation class to setup expiration call.
        '''
        return state.agent.get_time()

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
    def __repr__(self, state):
        return "<Resources. Totals: %r, Allocations: %r>" %\
               (state.totals, state.allocations)

    @replay.immutable
    def __eq__(self, state, other):
        if not isinstance(other, type(self)):
            return NotImplemented
        os = other._get_state()
        return os.totals == state.totals and\
               os.allocations == state.allocations


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
class Allocation(log.Logger, replay.Replayable):

    default_timeout = 10

    def __init__(self, parent, **resources):
        log.Logger.__init__(self, parent)
        replay.Replayable.__init__(self, parent, **resources)

        self._expiration_call = None

    def init_state(self, state, parent, **resources):
        state.parent = parent
        for name in resources:
            parent.check_name_exists(name)
            if not isinstance(resources[name], int):
                raise DeclarationError(
                    'Resource value should be int, got %r instead.' %\
                    resources[name].__class__)

        state.resources = resources
        state.parent.append_allocation(self)
        self._set_state(AllocationState.preallocated)

    @replay.side_effect
    def initiate(self):
        expiration_time = self._get_time() + self.default_timeout
        self._setup_expiration_call(expiration_time, self._on_timeout)

    # StateMachine implementation consitent with replayability

    @replay.mutable
    def _set_state(self, state, status):
        state.state = status

    @replay.immutable
    def get_state(self, state):
        return state.state

    @replay.immutable
    def _ensure_state(self, state, states):
        if self._cmp_state(states):
            return True
        raise RuntimeError("Expected state in: %r, was: %r instead" %\
                           (states, state.state))

    @replay.immutable
    def _cmp_state(self, state, states):
        if not isinstance(states, list):
            states = [states]
        if state.state in states:
            return True
        return False

    # ExpirationCalls implementations using replayability

    def _cancel_expiration_call(self):
        ec = self._expiration_call
        if ec and not (ec.called or ec.cancelled):
            ec.cancel()
            self._expiration_call = None

    def _setup_expiration_call(self, expiration_time, method):
        assert callable(method)
        time_left = expiration_time - self._get_time()
        self._expiration_call = delay.callLater(time_left, method)

    @replay.immutable
    def _get_time(self, state):
        return state.parent.get_time()

    # public API

    def confirm(self):
        self._ensure_state(AllocationState.preallocated)
        self._cancel_expiration_call()
        self._set_state(AllocationState.allocated)

    def release(self):
        self._set_state(AllocationState.released)
        self._cancel_expiration_call()
        self._cleanup()

    def _on_timeout(self):
        self.info('Preallocation of %r has reached its timeout.', self)
        self._set_state(AllocationState.expired)
        self._cleanup()

    @replay.immutable
    def get_resources(self, state):
        return state.resources

    @replay.immutable
    def _cleanup(self, state):
        state.parent.remove_allocation(self)

    @replay.immutable
    def __repr__(self, state):
        return "<Allocation state: %r, Resource: %r>" %\
               (state.state.name, state.resources, )

    @replay.immutable
    def __eq__(self, state, other):
        if not isinstance(other, type(self)):
            return NotImplemented
        os = other._get_state()
        return state.state == os.state and state.resources == os.resources

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
