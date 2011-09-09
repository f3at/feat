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
from feat.common import (decorator, annotate, guard, journal, reflect, )

from feat.interface.journal import *


@decorator.simple_function
def mutable(function):
    '''Combined decorator of guarded.mutable and journal.recorded.

    When called from outside a recording context, it returns a Deferred.
    When called from inside a recording context, it returns a L{fiber.Fiber}
    or any synchronous value.

    Same as using::

      @journal.recorded()
      @guard.mutable
      def spam(self, state, some, args):
          pass
    '''

    guard_wrapper = guard.mutable(function)

    # Register the function
    canonical = reflect.class_canonical_name(3)
    annotate.injectClassCallback("recorded", 4,
                                 "_register_recorded_call", guard_wrapper,
                                 class_canonical_name=canonical)

    def wrapper(self, *args, **kwargs):
        recorder = IRecorder(self)
        return recorder.call(guard_wrapper, args, kwargs)

    return wrapper


@decorator.simple_function
def entry_point(function):
    '''Combined decorator of guarded.mutable and journal.recorded
    that ensure the call is not reentrant.

    If a function decorated with it is called from inside a recording
    context it will raise L{f.i.j.ReentrantCallError}.

    Because the function cannot be called from inside a recording context,
    it always returns a Deferred.

    Same as using::

      @journal.recorded(reentrant=False)
      @guard.mutable
      def spam(self, state, some, args):
          pass
    '''

    guard_wrapper = guard.mutable(function)

    # Register the function
    canonical = reflect.class_canonical_name(3)
    annotate.injectClassCallback("recorded", 4,
                                 "_register_recorded_call", guard_wrapper,
                                 class_canonical_name=canonical)

    def wrapper(self, *args, **kwargs):
        recorder = IRecorder(self)
        return recorder.call(guard_wrapper, args, kwargs, reentrant=False)

    return wrapper


# Copy immutable decorator as-is from guarded module
immutable = guard.immutable
journaled = mutable
side_effect = journal.side_effect
named_side_effect = journal.named_side_effect
resolve_function = journal.resolve_function


# Copy the replay function for calling methods in replay context
replay = journal.replay


class Replayable(journal.Recorder, guard.Guarded):

    __metaclass__ = type('MetaReplayable', (type(journal.Recorder),
                                            type(guard.Guarded), ), {})

    def __init__(self, parent, *args, **kwargs):
        journal.Recorder.__init__(self, parent)
        guard.Guarded.__init__(self, parent, *args, **kwargs)

    def snapshot(self):
        return journal.Recorder.snapshot(self), guard.Guarded.snapshot(self)

    def recover(self, snapshot):
        s1, s2 = snapshot
        journal.Recorder.recover(self, s1)
        guard.Guarded.recover(self, s2)
