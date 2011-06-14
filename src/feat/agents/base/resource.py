# -*- Mode: Python -*-
# vi:si:et:sw=4:sts=4:ts=4
import copy

from feat.common import (log, serialization, error_handler, fiber, manhole, )
from feat.agents.base import replay
from feat.common.container import ExpDict


class AgentMixin(object):

    def initiate(self, state):
        state.resources = Resources(self)

    @replay.mutable
    def preallocate_resource(self, state, **params):
        return state.resources.preallocate(**params)

    @replay.mutable
    def allocate_resource(self, state, **params):
        return state.resources.allocate(**params)

    @replay.immutable
    def check_allocation_exists(self, state, allocation_id):
        return state.resources.get_allocation(allocation_id)

    @manhole.expose()
    @replay.immutable
    def get_resource_usage(self, state):
        return state.resources.get_usage()

    @replay.immutable
    def list_resource(self, state):
        allocated = state.resources.allocated()
        totals = state.resources.get_totals()
        return totals, allocated

    @replay.mutable
    def confirm_allocation(self, state, allocation_id):
        return state.resources.confirm(allocation_id)

    @replay.immutable
    def allocation_used(self, state, allocation_id):
        '''
        Checks if allocation is used by any of the partners.
        If allocation does not exist returns False.
        @param allocation_id: ID of the allocation
        @returns: True/False
        '''
        return len(filter(lambda x: x.allocation_id == allocation_id,
                          state.partners.all)) > 0

    @replay.mutable
    def release_resource(self, state, allocation_id):
        return state.resources.release(allocation_id)

    @replay.mutable
    def premodify_allocation(self, state, allocation_id, **delta):
        return state.resources.premodify(allocation_id, **delta)

    @replay.mutable
    def apply_modification(self, state, change_id):
        return state.resources.apply_modification(change_id)

    @replay.mutable
    def release_modification(self, state, change_id):
        return state.resources.release_modification(change_id)


@serialization.register
class Resources(log.Logger, log.LogProxy, replay.Replayable):

    def __init__(self, agent):
        log.Logger.__init__(self, agent)
        log.LogProxy.__init__(self, agent)
        replay.Replayable.__init__(self, agent)

    def init_state(self, state, agent):
        state.agent = agent
        # resource_name -> total
        state.totals = dict()
        # allocation_id -> allocation
        state.id_autoincrement = 1
        # contains preallocations and allocation_changes
        state.modifications = ExpDict(agent)

    @replay.immutable
    def restored(self, state):
        log.Logger.__init__(self, state.agent)
        log.LogProxy.__init__(self, state.agent)
        replay.Replayable.restored(self)

    # Public API

    @replay.immutable
    def get_usage(self, state):

        def update(d, delta):
            for k, v in delta.iteritems():
                if k not in d:
                    d[k] = v
                else:
                    d[k] += v

        # Compute current deltas per resources
        deltas = {}
        for alloc in state.modifications.itervalues():
            if isinstance(alloc, Allocation):
                update(deltas, alloc.resources)
            elif isinstance(alloc, AllocationChange):
                update(deltas, alloc.delta)

        # Compute current allocation per resources
        allocated = {}
        for alloc in state.agent.get_descriptor().allocations.itervalues():
            update(allocated, alloc.resources)

        result = {}
        for name, total in state.totals.iteritems():
            pre = deltas.get(name, 0)
            curr = allocated.get(name, 0)
            result[name] = (total, curr, pre)
        return result

    @replay.immutable
    def get_totals(self, state):
        return copy.copy(state.totals)

    @replay.mutable
    def preallocate(self, state, **params):
        try:
            self._validate_params(params)
            allocation = Allocation(id=self._next_id(), **params)
            self._append_allocation(allocation)
            return allocation
        except NotEnoughResources:
            return None

    @replay.mutable
    def confirm(self, state, allocation_id):
        '''
        confirms a preallocation
        '''
        allocation = state.modifications.get(allocation_id, None)
        if allocation == None or not isinstance(allocation, Allocation):
            return fiber.fail(AllocationNotFound(
                    'Expired or non-existent allocation_id=%s' %\
                            allocation_id))
        self._remove_modification(allocation_id)

        f = fiber.Fiber()
        f.add_callback(self._append_allocation_to_descriptor)
        return f.succeed(allocation)

    @replay.mutable
    def apply_modification(self, state, alloc_change_id):
        alloc_change = state.modifications.get(alloc_change_id, None)
        if alloc_change == None or\
            not isinstance(alloc_change, AllocationChange):
            return fiber.fail(AllocationChangeNotFound(
                    'Expired or non-existent modification_id=%s' %\
                            alloc_change_id))
        self._remove_modification(alloc_change_id)

        f = fiber.Fiber()
        f.add_callback(self._modify_allocation_in_descriptor)
        return f.succeed(alloc_change)

    @replay.mutable
    def allocate(self, state, **params):
        try:
            self._validate_params(params)
            allocation = Allocation(id=self._next_id(), **params)
            self._validate(state.totals, self._read_allocations().values() +
                    [allocation], state.modifications)
        except BaseResourceException as e:
            return fiber.fail(e)
        f = fiber.Fiber()
        f.add_callback(self._append_allocation_to_descriptor)
        return f.succeed(allocation)

    def get_allocation(self, allocation_id):
        '''
        Check that confirmed allocation with given id exists.
        Raise exception otherwise.
        '''
        try:
            allocation = self._read_allocations().get(allocation_id, None)
            if allocation is None:
                raise AllocationNotFound(
                    'Allocation with id=%s not found' % allocation_id)
            return fiber.succeed(allocation)
        except AllocationNotFound as e:
            return fiber.fail(e)

    @replay.mutable
    def release(self, state, allocation_id):
        '''
        Used to release allocations or preallocations
        '''
        allocation = self._find_allocation(allocation_id)
        f = fiber.succeed()
        if allocation_id in self._read_allocations():
            f.add_callback(fiber.drop_param,
                        self._remove_allocation_from_descriptor, allocation)
        else:
            f.add_callback(fiber.drop_param,
                        self._remove_modification, allocation_id)
        return f

    @replay.mutable
    def release_modification(self, state, change_id):
        self._remove_modification(change_id)

    @replay.mutable
    def _remove_modification(self, state, change_id):
        mod = state.modifications.pop(change_id, None)
        if mod is None:
            raise AllocationNotFound(
                    'Expired or non-existenr modification with id=%s ' %\
                            change_id)

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

    def allocated(self, totals=None, allocations=None, modifications=None):
        '''
        allocations : allocated
        modifications : preallocations and allocation changes
        '''
        totals, allocations, modifications = self._unpack_defaults(totals,
                                                allocations, modifications)
        result = dict()
        for name in totals:
            result[name] = 0
        for allocation in allocations:
            allocation.add_to(result)
        for m in modifications:
            modifications[m].add_to(result)
        return result

    # ENDOF Public API

    @replay.immutable
    def get_allocations(self, state):
        return self._read_allocations()

    @replay.immutable
    def get_modifications(self, state):
        return copy.copy(state.modifications)

    @replay.mutable
    def premodify(self, state, allocation_id, **delta):
        try:
            self._validate_params(delta)
            self._find_allocation(allocation_id)
            alloc_change = AllocationChange(self._next_id(),
                        allocation_id, **delta)
            self._append_modification(alloc_change)
            return alloc_change
        except NotEnoughResources:
            return None

    # handling allocation list in descriptor

    @replay.journaled
    def _append_allocation_to_descriptor(self, state, allocation):

        def do_append(desc, allocation):
            desc.allocations[allocation.id] = allocation
            return allocation

        f = fiber.Fiber()
        f.add_callback(state.agent.update_descriptor, allocation)
        return f.succeed(do_append)

    @replay.journaled
    def _remove_allocation_from_descriptor(self, state, allocation):

        def do_remove(desc, allocation):
            if allocation.id not in desc.allocations:
                self.warning('Tried to remove allocation %r from descriptor, '
                             'but the allocation are: %r',
                             allocation, desc.allocations)
                return
            del(desc.allocations[allocation.id])
            return allocation

        f = fiber.Fiber()
        f.add_callback(state.agent.update_descriptor, allocation)
        return f.succeed(do_remove)

    @replay.journaled
    def _modify_allocation_in_descriptor(self, state, alloc_change):

        def do_update(desc, alloc_change):
            alloc_id = alloc_change.allocation_id
            if alloc_id not in desc.allocations:
                self.warning('Tried to update allocation %r in descriptor, '
                             'but the allocations are: %r',
                             alloc_id, desc.allocations)
                return

            delta = alloc_change.delta
            al = desc.allocations[alloc_id]
            for r in delta:
                if r not in al.resources:
                    al.resources[r] = delta[r]
                else:
                    al.resources[r] += delta[r]
                if al.resources[r] < 0:
                    al.resources[r] = 0
            return al

        f = fiber.Fiber()
        f.add_callback(state.agent.update_descriptor, alloc_change)
        return f.succeed(do_update)

    # Methods for maintaining the allocations inside

    def _validate(self, totals=None, allocations=None, modifications=None):
        totals, allocations, modifications = self._unpack_defaults(totals,
                                                allocations, modifications)

        allocated = self.allocated(totals, allocations, modifications)
        errors = list()
        for name in totals:
            if allocated[name] > totals[name]:
                errors.append('Not enough %r. Allocated already: %d. '
                              'New value: %d.' %\
                              (name, allocated[name], totals[name], ))
        if len(errors) > 0:
            raise NotEnoughResources(' '.join(errors))

    @replay.immutable
    def _read_allocations(self, state):
        allocations = state.agent.get_descriptor().allocations
        return allocations

    @replay.mutable
    def _next_id(self, state):
        ret = state.id_autoincrement
        state.id_autoincrement += 1
        return str(ret)

    @replay.immutable
    def _find_allocation(self, state, allocation_id):
        """
        Search for an allocation or a preallocation
        @returns: Allocation object
        """
        allocation = self._read_allocations().get(allocation_id, None)
        if allocation is None:
            preallocation = state.modifications.get(allocation_id, None)
            if preallocation is not None:
                if isinstance(preallocation, AllocationChange):
                    raise AllocationTypeError(
                        'Incorect type of allocation with id=%s' %\
                                allocation_id)
                return preallocation
            raise AllocationNotFound(
                'Allocation with id=%s not found' % allocation_id)
        return allocation

    @replay.mutable
    def _append_allocation(self, state, allocation):
        if not isinstance(allocation, Allocation):
            raise ValueError('Expected Allocation class, got %r instead!' %\
                             allocation.__class__, )

        self._validate(state.totals, self._read_allocations().values() +
                [allocation], state.modifications)
        state.modifications.set(allocation.id, allocation,
                expiration=allocation.default_timeout, relative=True)

    @replay.mutable
    def _append_modification(self, state, alloc_change):
        if not isinstance(alloc_change, AllocationChange):
            raise ValueError('Expected AllocationChange class,\
                    got %r instead!' % alloc_change.__class__, )

        self._validate(state.totals, self._read_allocations().values() +
                [Allocation(None, **alloc_change.delta)], state.modifications)
        state.modifications.set(alloc_change.id, alloc_change,
                expiration=alloc_change.default_timeout, relative=True)

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
    def _unpack_defaults(self, state, totals, allocations, modifications):
        """
        @allocations:  list of allocations (Allocations)
        @modifications: Allocations and allocation changes (AllocationChange)
        """
        if totals is None:
            totals = state.totals
        if allocations is None:
            allocations = self._read_allocations().values()
        if modifications is None:
            modifications = state.modifications
        return totals, allocations, modifications

    @replay.immutable
    def _check_resource_exists(self, state, name):
        if name not in state.totals:
            raise UnknownResource('Unknown resource name: %r.' % name)

    @replay.immutable
    def __repr__(self, state):
        return "<Resources. Totals: %r>" %\
               (state.totals, )

    @replay.immutable
    def __eq__(self, state, other):
        if not isinstance(other, type(self)):
            return NotImplemented
        os = other._get_state()
        if os.totals != state.totals:
            return False
        if state.modifications != os.modifications:
            return False
        return True

    def __ne__(self, other):
        if type(self) != type(other):
            return NotImplemented
        return not self.__eq__(other)


@serialization.register
class Allocation(serialization.Serializable):

    type_name = 'alloc'

    default_timeout = 10
    _error_handler=error_handler

    def __init__(self, id=None, **resources):
        self.id = id
        self.resources = resources

    def add_to(self, total):
        for r in self.resources:
            total[r] += self.resources[r]
        return total

    def __repr__(self):
        return "<Allocation id: %r, Resource: %r>" %\
               (self.id, self.resources, )

    def __eq__(self, other):
        if not isinstance(other, type(self)):
            return NotImplemented
        return self.resources == other.resources and \
               self.id == other.id

    def __ne__(self, other):
        return not self.__eq__(other)


@serialization.register
class AllocationChange(serialization.Serializable):

    type_name = 'alloc_change'

    default_timeout = 10

    def __init__(self, id, allocation_id=None, **delta):

        self.id = id
        self.allocation_id = allocation_id
        self.delta = delta

    def add_to(self, total):
        for r in self.delta:
            total[r] += max(0, self.delta[r])
        return total

    def __eq__(self, other):
        if not isinstance(other, type(self)):
            return NotImplemented
        return self.id == other.id and \
               self.allocation_id == other.allocation_id and \
               self.delta == other.delta

    def __ne__(self, other):
        if type(self) != type(other):
            return NotImplemented
        return not self.__eq__(other)


class BaseResourceException(Exception):
    pass


class NotEnoughResources(BaseResourceException):
    pass


class UnknownResource(BaseResourceException):
    pass


class DeclarationError(BaseResourceException):
    pass


class AllocationNotFound(BaseResourceException):
    pass


class AllocationChangeNotFound(BaseResourceException):
    pass


class AllocationTypeError(BaseResourceException):
    pass
