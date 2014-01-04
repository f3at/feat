# F3AT - Flumotion Asynchronous Autonomous Agent Toolkit
# Copyright (C) 2010,2011 Flumotion Services, S.A.
# All rights reserved.

# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License along
# with this program; if not, write to the Free Software Foundation, Inc.,
# 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA.

# See "LICENSE.GPL" in the source distribution for more information.

# Headers in this file shall remain intact.
# -*- Mode: Python -*-
# vi:si:et:sw=4:sts=4:ts=4

import sys

from pprint import pformat

from zope.interface import Interface, implements, Attribute, classProvides

from feat.common import log, serialization, fiber
from feat.agents.base import replay
from feat.common.container import ExpDict
from feat.agents.application import feat


ALLOCATION_TIMEOUT = 10


class IResourceDefinitionFactory(Interface):

    def __call__(name, *args, **kwargs):
        '''
        @return: L{IResourceDefinition}
        '''


class IResourceDefinition(Interface):

    name = Attribute("resource name")

    def allocate(allocations, *args):
        """
        Generate IAllocatedResource object for the given parameters.
        The params will differ for different types of resource.

        This method should raise NotEnoughResource in case it cannot comply
        or DeclarationError if argument doesn't make sense.

        @param: [L{IAllocatedResource}]
        @return: L{IAllocatedResource}
        """

    def modify(allocations, resource, *args):
        """
        Generate IAllocatedResource representing change done in the allocated
        resource.

        This method may raise NotEnoughResource or DeclarationError.

        @param allocations: [L{IAllocatedResource}] list of allocated and
                            preallocated and modified resources.
        @param resource: The resource being modified or None in case Allocation
                         doesn't include this resource.
        @return: L{IAllocatedResource}
        """

    def reduce(allocations):
        '''
        Reduce list of IAllocatedResource to single displayable value.
        '''

    def get_total():
        '''
        Give object representing the total available.
        '''

    def zero():
        """
        Return a new instance of IAllocatedResource representing the zero
        element of the group.
        """


class IAllocatedResource(Interface):

    def extract_init_arguments():
        """
        Should return whatever params are necessary to pass to
        IResourceDefinition's allocate() method to recreate the
        analogical allocation.
        """

    def add(other):
        """
        Generalized add operator. This is used to modify allocation.
        @return: bool value indicating if the resource allocation in non-zero
        """

    def zero():
        """
        Return a new instance of IAllocatedResource representing the zero
        element of the group.
        """

    def get_delta(*args):
        """
        Return the parametrs to be passed to modify method to get as the
        result the IAllocatedResource analogical to the one created with args.
        Represents the substraction operation of the group.
        """


@feat.register_restorator
class Range(serialization.Serializable):
    implements(IResourceDefinition)
    classProvides(IResourceDefinitionFactory)

    type_name = 'range_def'

    def __init__(self, name, first, last):
        self.name = name
        first = int(first)
        last = int(last)
        if first < 0 or last < 0:
            raise DeclarationError("%r and %r needs to be positive integers!"
                                   % (first, last))
        elif first > last:
            raise DeclarationError("%r > %r!" % (first, last))

        self.first = first
        self.last = last

    ### IResourceDefinition ###

    def allocate(self, allocations, number):
        values = self._find_free_values(allocations, number)
        return AllocatedRange(values)

    def modify(self, allocations, resource, *args):
        '''
        Correct format of args here is:
        cmd1, param1, param2, cmd2, param1, ...
        Supported commands:
         - add - allocate specified number of random values more
         - add_specific - allocate specific value
         - release - release allocated specific value
        '''
        res = RangeModification()
        last_cmd = None
        for param in args:
            if isinstance(param, (str, unicode, )):
                last_cmd = param
            elif last_cmd is None:
                raise DeclarationError("First parameter should be a command")
            elif last_cmd == 'add':
                values = self._find_free_values(allocations, param)
                for p in values:
                    res.add_value(p)
            elif last_cmd == 'add_specific':
                if not self._value_free(allocations, param):
                    raise NotEnoughResource(
                        'Value %r of resource %s is allocated' %
                        (param, self.name, ))
                if param in resource.values:
                    raise DeclarationError('Value %s is already included '
                                           'in %r' % (param, resource))
                res.add_value(param)
            elif last_cmd == 'release':
                if not param in resource.values:
                    raise DeclarationError('Value %s is not included '
                                           'in %r' % (param, resource))
                res.add_value(-param)
            else:
                raise DeclarationError("Unknown modify command: %s" %
                                       (last_cmd, ))
        return res

    def reduce(self, allocations):
        # gives list of allocated values
        return [x for x in range(self.first, self.last + 1)
                if not self._value_free(allocations, x)]

    def get_total(self):
        return (self.first, self.last)

    @staticmethod
    def zero():
        return AllocatedRange()

    ### private ####

    def _find_free_values(self, allocations, number):
        to_allocate = number
        res = list()
        for x in range(self.first, self.last + 1):
            if number < 1:
                break
            if self._value_free(allocations, x):
                res.append(x)
                number -= 1

        if number > 0:
            total_allocated = self.last - self.first - to_allocate + number
            raise NotEnoughResource('Not enough %s. Allocated already: %d '
                                    'Tried to allocate: %d' %
                                    (self.name, total_allocated, to_allocate))
        return res

    def _value_free(self, allocations, value):
        included = any(map(lambda x: value in x.values, allocations))
        return not included

    def __eq__(self, other):
        if not isinstance(other, type(self)):
            return NotImplemented
        return self.name == other.name and \
               self.first == other.first and \
               self.last == other.last

    def __ne__(self, other):
        if not isinstance(other, type(self)):
            return NotImplemented
        return not self.__eq__(other)


@feat.register_restorator
class Scalar(serialization.Serializable):
    implements(IResourceDefinition)
    classProvides(IResourceDefinitionFactory)

    type_name = 'scalar_def'

    def __init__(self, name, total):
        self.name = name
        try:
            self.total = int(total)
            if self.total < 0:
                raise ValueError("Should be positive integer")
        except ValueError as e:
            raise DeclarationError("Bad total: %s. Exp: %r"
                                   % (total, e, )), None, sys.exc_info()[2]

    ### IResourceDefinition ###

    def allocate(self, allocations, value):
        try:
            value = int(value)
            if value <= 0:
                raise ValueError("Should be positive integer")
        except ValueError as e:
            raise DeclarationError("Bad ammount: %s. Exp: %r"
                                   % (value, e, )), None, sys.exc_info()[2]

        total_allocated = self.reduce(allocations)
        if self.total < total_allocated + value:
            raise NotEnoughResource('Not enough %s. Allocated already: %d '
                                    'New value: %d' %
                                    (self.name, total_allocated,
                                     total_allocated + value))
        return AllocatedScalar(value)

    def modify(self, allocations, resource, value):
        try:
            value = int(value)
            current_value = resource.value if resource else 0
            if -value > current_value:
                raise ValueError("Tried to release more than was allocated.")
        except ValueError as e:
            raise DeclarationError("Bad ammount: %s. Exp: %r" % (value, e, ))
        total_allocated = self.reduce(allocations)
        if self.total < total_allocated + value:
            raise NotEnoughResource('Not enough %s. Allocated already: %d '
                                    'New value: %d' %
                                    (self.name, total_allocated,
                                     total_allocated + value))
        return ScalarModification(value)

    def reduce(self, allocations):
        return sum([max([x.value, 0]) for x in allocations])

    def get_total(self):
        return self.total

    @staticmethod
    def zero():
        return AllocatedScalar(0)

    ### private ####

    def __eq__(self, other):
        if not isinstance(other, type(self)):
            return NotImplemented
        return self.name == other.name and \
               self.total == other.total

    def __ne__(self, other):
        if not isinstance(other, type(self)):
            return NotImplemented
        return not self.__eq__(other)


@feat.register_restorator
class AllocatedRange(serialization.Serializable):
    implements(IAllocatedResource)

    type_name = 'range'

    def __init__(self, values=list()):
        self.values = set(values)

    ### IAllocatedResource ###

    def extract_init_arguments(self):
        return (len(self.values), )

    @staticmethod
    def zero():
        return Range.zero()

    def add(self, other):
        for val in other.values:
            if val > 0:
                if val in self.values:
                    raise ValueError("%r already in %r" % (val, self.values))
                self.values.add(val)
            else:
                if -val not in self.values:
                    raise ValueError("%r not in %r" % (-val, self.values))
                self.values.remove(-val)
        return len(self.values) > 0

    def get_delta(self, values):
        delta = len(self.values) - values
        if delta > 0:
            return ('release', delta)
        elif delta < 0:
            return ('add', -delta)

    ### public ###

    def add_value(self, value):
        self.values.add(value)

    def __repr__(self):
        return str(self.values)

    def __eq__(self, other):
        if not isinstance(other, type(self)):
            return NotImplemented
        return self.values == other.values

    def __ne__(self, other):
        if not isinstance(other, type(self)):
            return NotImplemented
        return not self.__eq__(other)


@feat.register_restorator
class AllocatedScalar(serialization.Serializable):
    implements(IAllocatedResource)

    type_name = 'scalar'

    def __init__(self, value):
        self.value = value

    ### IAllocatedResource ###

    def extract_init_arguments(self):
        return (self.value, )

    @staticmethod
    def zero():
        return Scalar.zero()

    def add(self, other):
        tmp = self.value + other.value
        if tmp < 0:
            raise ValueError("Value needs to be positive. Got %r", tmp)
        self.value = tmp
        return not self.value == 0

    def get_delta(self, value):
        return value - self.value

    ### private ###

    def __repr__(self):
        return str(self.value)

    def __eq__(self, other):
        if not isinstance(other, type(self)):
            return NotImplemented
        return self.value == other.value

    def __ne__(self, other):
        if not isinstance(other, type(self)):
            return NotImplemented
        return not self.__eq__(other)


@feat.register_restorator
class ScalarModification(AllocatedScalar):

    type_name = 'scalar_change'


@feat.register_restorator
class RangeModification(AllocatedRange):

    type_name = 'range_change'


@feat.register_restorator
class Allocation(serialization.Serializable):

    type_name = 'alloc'

    def __init__(self, id=None, **allocated):
        self.id = id
        for key, r_a in allocated.iteritems():
            if not IAllocatedResource.providedBy(r_a):
                raise ValueError("Incorrect param, key: %s, value: %r, does "
                                 "not provide IAllocatedResource." %
                                 (key, r_a, ))

        # name -> IAllocatedResource
        self.alloc = allocated

    def allocated_for(self, name):
        '''
        Give IAllocatedResource object for the given name or None.
        '''
        return self.alloc.get(name, None)

    def apply(self, change):
        if not isinstance(change, AllocationChange):
            raise TypeError("Expected argument 1 to be AllocationChange, got "
                            "%r" % change)
        for name, delta in change.deltas.items():
            if name not in self.alloc:
                self.alloc[name] = delta.zero()

        for name, alloc in self.alloc.items():
            if name in change.deltas:
                if not alloc.add(change.deltas[name]):
                    del(self.alloc[name])

        return self

    def __repr__(self):
        return "<Allocation id: %r, Alloc: %s>" %\
               (self.id, pformat(self.alloc), )

    def __eq__(self, other):
        if not isinstance(other, type(self)):
            return NotImplemented
        return self.alloc == other.alloc and \
               self.id == other.id

    def __ne__(self, other):
        return not self.__eq__(other)


@feat.register_restorator
class AllocationChange(serialization.Serializable):

    type_name = 'alloc_change'

    def __init__(self, id, allocation_id=None, **deltas):
        self.id = id
        self.allocation_id = allocation_id
        for key, r_a in deltas.iteritems():
            if not IAllocatedResource.providedBy(r_a):
                raise ValueError("Incorrect param, key: %s, value: %r, does "
                                 "not provide IAllocatedResource." %
                                 (key, r_a, ))
        self.deltas = deltas

    def allocated_for(self, name):
        '''
        Give IAllocatedResource object for the given name or None.
        '''
        return self.deltas.get(name, None)

    def __eq__(self, other):
        if not isinstance(other, type(self)):
            return NotImplemented
        return self.id == other.id and \
               self.allocation_id == other.allocation_id and \
               self.deltas == other.deltas

    def __ne__(self, other):
        if type(self) != type(other):
            return NotImplemented
        return not self.__eq__(other)

    def __repr__(self):
        return "<Change id: %r, A_ID: %s, Deltas: %s>" %\
               (self.id, self.allocation_id, pformat(self.deltas), )


class AgentMixin(object):

    @replay.mutable
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
        return state.resources.check_allocated(allocation_id)

    @replay.immutable
    def get_resource_usage(self, state):
        return state.resources.get_usage()

    @replay.immutable
    def get_allocation(self, state, allocation_id):
        return state.resources.get_allocation(allocation_id)

    @replay.immutable
    def get_allocation_delta(self, state, allocation_id, **resource):
        return state.resources.get_allocation_delta(allocation_id, **resource)

    @replay.immutable
    def get_allocation_expiration(self, state, allocation_id):
        return state.resources.get_allocation_expiration(allocation_id)

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
        return state.resources.confirm(change_id)

    @replay.mutable
    def release_modification(self, state, change_id):
        return state.resources.release(change_id)


@feat.register_restorator
class Resources(log.Logger, log.LogProxy, replay.Replayable):

    ignored_state_keys = ['agent']

    preallocation_timeout = ALLOCATION_TIMEOUT

    def __init__(self, agent):
        log.Logger.__init__(self, agent)
        log.LogProxy.__init__(self, agent)
        replay.Replayable.__init__(self, agent)

    def init_state(self, state, agent):
        state.agent = agent
        # resource_name -> IResource
        state.definitions = dict()
        state.id_autoincrement = 1
        # id -> temporal_objects (Allocation)
        state.modifications = ExpDict(agent)

    @replay.immutable
    def restored(self, state):
        log.Logger.__init__(self, state.agent)
        log.LogProxy.__init__(self, state.agent)
        replay.Replayable.restored(self)

    # Public API

    @replay.mutable
    def define(self, state, name, factory, *args, **kwargs):
        factory = IResourceDefinitionFactory(factory)
        definition = factory(name, *args, **kwargs)
        self.log("Appending definition of resource name %r, with "
                 "definition %r", name, definition)
        if name in state.definitions:
            self.log("Overwriting old definition.")
        state.definitions[name] = definition

    @replay.mutable
    def preallocate(self, state, **params):
        '''
        keywords: the values of keywords will be passed to corresponding
                  resource definitions.
        '''
        try:
            alloc = self._generate_allocation(**params)
            state.modifications.set(alloc.id, alloc,
                                    expiration=self.preallocation_timeout,
                                    relative=True)
            return alloc
        except NotEnoughResource:
            return None

    @replay.mutable
    def confirm(self, state, allocation_id):
        alloc = state.modifications.pop(allocation_id, None)
        if alloc is None:
            alloc = self._get_confirmed().get(allocation_id, None)
            if alloc is not None:
                self.log('confirm() called on already confirmed allocation. '
                         'Ignoring.')
                return fiber.succeed(alloc)

            raise AllocationNotFound("Allocation with id=%s not found" %
                                     allocation_id)
        return self._append_to_descriptor(alloc)

    @replay.mutable
    def allocate(self, state, **params):
        alloc = self._generate_allocation(**params)
        return self._append_to_descriptor(alloc)

    @replay.mutable
    def premodify(self, state, allocation_id, **params):
        allocs = self._get_confirmed()
        alloc = allocs.get(allocation_id, None)
        if alloc is None:
            raise AllocationNotFound("Allocation with id=%s not found" %
                                     allocation_id)
        try:
            change = self._generate_allocation_change(alloc, **params)
            state.modifications.set(change.id, change,
                                    expiration=ALLOCATION_TIMEOUT,
                                    relative=True)
            return change
        except NotEnoughResource:
            return None

    @replay.mutable
    def get_allocation_delta(self, state, allocation_id, **resource):
        deltas = dict()
        alloc = self.get_allocation(allocation_id)
        for name, args in resource.iteritems():
            definition = self._get_definition(name)
            if not isinstance(args, (tuple, list)):
                args = (args, )
            alloc_resource = alloc.alloc.get(name, None)
            if alloc_resource is None:
                alloc_resource = definition.zero()
            delta = alloc_resource.get_delta(*args)
            if delta:
                deltas[name] = delta

        for name, alloc_resource in alloc.alloc.iteritems():
            if name not in resource:
                definition = self._get_definition(name)
                args = definition.zero().extract_init_arguments()
                deltas[name] = alloc_resource.get_delta(*args)
        return deltas

    @replay.immutable
    def check_allocated(self, state, allocation_id):
        '''
        Check that confirmed allocation with given id exists.
        Raise exception otherwise.
        '''
        allocs = self._get_confirmed()
        return allocation_id in allocs

    @replay.immutable
    def get_allocation(self, state, allocation_id):
        allocs = self._get_confirmed()
        try:
            return allocs[allocation_id]
        except KeyError:
            raise AllocationNotFound("Allocation with id=%s not found" %
                                     allocation_id), None, sys.exc_info()[2]

    @replay.immutable
    def get_allocation_expiration(self, state, allocation_id):
        return state.modifications.get_expiration(allocation_id)

    @replay.mutable
    def release(self, state, allocation_id):
        '''
        Used to release allocations, preallocations and modifications.
        '''
        confirmed = self.check_allocated(allocation_id)
        transient = allocation_id in state.modifications

        if confirmed:
            to_remove = self._get_confirmed()[allocation_id]
            return self._remove_allocation_from_descriptor(to_remove)
        if transient:
            del(state.modifications[allocation_id])
            return
        raise AllocationNotFound("Allocation with id=%s not found" %
                                 allocation_id)

    @replay.immutable
    def allocated(self, state):
        resp = dict()
        for x in state.definitions.itervalues():
            allocs = self._get_allocated(x.name)
            resp[x.name] = x.reduce(allocs)
        return resp

    @replay.immutable
    def get_usage(self, state):
        resp = dict()
        for x in state.definitions.itervalues():
            alloc = self._get_allocated(x.name)
            modif = self._get_modified(x.name)
            resp[x.name] = (x.type_name, x.get_total(),
                            x.reduce(alloc), x.reduce(modif))
        return resp

    ### methods used by tests ###

    @replay.immutable
    def get_totals(self, state):
        return dict((x.name, x.get_total())
                    for x in state.definitions.itervalues())

    @replay.immutable
    def preallocated(self, state):
        resp = dict()
        for x in state.definitions.itervalues():
            allocs = self._get_modified(x.name)
            resp[x.name] = x.reduce(allocs)
        return resp

    ### handling allocation list in descriptor ###

    @replay.journaled
    def _append_to_descriptor(self, state, allocation):

        def do_append(desc, allocation):
            desc.allocations[allocation.id] = allocation
            return allocation

        def do_apply_modification(desc, change):
            alloc = desc.allocations[change.allocation_id]
            alloc = alloc.apply(change)
            desc.allocations[change.allocation_id] = alloc
            return alloc

        if isinstance(allocation, Allocation):
            action = do_append
        elif isinstance(allocation, AllocationChange):
            action = do_apply_modification
        else:
            raise TypeError("Unexpected type of argument 2, got %r." %
                            allocation)

        f = fiber.Fiber()
        f.add_callback(state.agent.update_descriptor, allocation)
        return f.succeed(action)

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

    ### private ###

    @replay.immutable
    def _get_confirmed(self, state):
        return state.agent.get_descriptor().allocations

    @replay.immutable
    def _generate_allocation(self, state, **params):
        '''
        this may raise NotEnoughResource or UnknownResource
        '''
        resource_allocations = dict()
        for name, args in params.iteritems():
            definition = self._get_definition(name)
            if not isinstance(args, (tuple, list)):
                args = (args, )

            allocated = self._get_allocated(name)
            allocated_resource = definition.allocate(allocated, *args)
            resource_allocations[name] = allocated_resource
        a_id = self._next_id()
        alloc = Allocation(a_id, **resource_allocations)
        return alloc

    @replay.immutable
    def _generate_allocation_change(self, state, alloc, **params):
        '''
        this may raise NotEnoughResource or UnknownResource
        '''
        deltas = dict()
        for name, args in params.iteritems():
            definition = self._get_definition(name)
            if not isinstance(args, (tuple, list)):
                args = (args, )

            allocated = self._get_allocated(name)
            resource = alloc.alloc.get(name, None)
            allocated_resource = definition.modify(allocated, resource, *args)
            deltas[name] = allocated_resource
        a_id = self._next_id()
        alloc = AllocationChange(a_id, alloc.id, **deltas)
        return alloc

    @replay.immutable
    def _get_definition(self, state, name):
        try:
            return state.definitions[name]
        except KeyError:
            raise UnknownResource('Unknown resource name: %r.'
                                  % name), None, sys.exc_info()[2]

    @replay.mutable
    def _next_id(self, state):
        ret = state.id_autoincrement
        state.id_autoincrement += 1
        return str(ret)

    @replay.immutable
    def _get_allocated(self, state, name):
        '''
        Gives list of IAllocatedResource objects for the given resource name.
        '''
        resp = list()
        allocations = self._get_confirmed().values() + \
                      state.modifications.values()
        for alloc in allocations:
            resp.append(alloc.allocated_for(name))
        return filter(None, resp)

    @replay.immutable
    def _get_modified(self, state, name):
        allocs = [a.allocated_for(name)
                  for a in state.modifications.itervalues()]
        return filter(None, allocs)

    ### python specific ###

    @replay.immutable
    def __repr__(self, state):
        return "<Resources>"

    @replay.immutable
    def __eq__(self, state, other):
        if not isinstance(other, type(self)):
            return NotImplemented
        os = other._get_state()
        if os.definitions != state.definitions:
            return False
        if state.modifications != os.modifications:
            return False
        return True

    def __ne__(self, other):
        if type(self) != type(other):
            return NotImplemented
        return not self.__eq__(other)


class BaseResourceException(Exception):
    pass


class NotEnoughResource(BaseResourceException):
    pass


class UnknownResource(BaseResourceException):
    pass


class AllocationNotFound(BaseResourceException):
    pass


class DeclarationError(BaseResourceException):
    pass
