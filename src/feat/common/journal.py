import weakref

from twisted.internet import defer
from zope.interface import implements

from feat.interface.fiber import *
from feat.interface.journal import *
from feat.interface.serialization import *
from feat.common.serialization.base import MetaSerializable
from feat.common.annotate import MetaAnnotable

from . import decorator, annotate, reflect, fiber, serialization

RECORDED_TAG = "__RECORDED__"
SIDE_EFFECTS_TAG = "__SIDE_EFFECTS__"
INSIDE_EFFECT_TAG = "__INSIDE_EFFECT__"


@decorator.parametrized_function
def recorded(function, custom_id=None, reentrant=True):
    '''MUST only be used only with method from child
    classes of L{{Recorder}}.'''

    annotate.injectClassCallback("recorded", 4,
                                 "_register_recorded_call",
                                 function, custom_id=custom_id)

    def wrapper(self, *args, **kwargs):
        recorder = IRecorder(self)
        return recorder.call(function, args, kwargs, reentrant=reentrant)

    return wrapper


@decorator.simple_callable
def side_effect(original):
    '''Decorator for function or method that do not modify the recorder state
    but have some side effects that can't be replayed.
    What it does in recording mode is keep the function name, arguments,
    keyword and result as a side effect that will be recorded in the journal.
    In replay mode, it will only pop the next expected side-effect, verify
    the function name, arguments and keywords and return the expected result
    without executing the real function code. If the function name, arguments
    or keywords were to be different than the expected ones, it would raise
    L{ReplayError}. Should work for any function or method.'''

    def check_result(result, info):
        if isinstance(result, defer.Deferred):
            raise SideEffectResultError("Side-effect functions %s "
                                        "cannot return Deferred" % info)
        if IFiber.providedBy(result):
            raise SideEffectResultError("Side-effect functions %s "
                                        "cannot return IFiber" % info)
        return result

    def wrapper(callable, *args, **kwargs):
        name = reflect.canonical_name(callable)

        section = fiber.WovenSection()
        section.enter()

        journal_mode = section.state.get(RECORDED_TAG, None)
        inside_flag = section.state.get(INSIDE_EFFECT_TAG, False)

        if inside_flag:
            # Already inside a side-effect call, so just abort and call
            section.abort()
            return check_result(callable(*args, **kwargs), name)

        if journal_mode == JournalMode.recording:
            # Recording mode, execute and record the side-effect
            side_effects = section.state[SIDE_EFFECTS_TAG]

            section.state[INSIDE_EFFECT_TAG] = True
            try:
                result = check_result(callable(*args, **kwargs), name)
            finally:
                section.state[INSIDE_EFFECT_TAG] = False

            side_effects.append((name, args or None, kwargs or None, result))
            return section.exit(result)

        if journal_mode == JournalMode.replay:
            # Replay mode, pop a side effect, verify the function name
            # and the arguments, and return the canned result without
            # executing the real code.
            side_effects = section.state[SIDE_EFFECTS_TAG]
            if not side_effects:
                raise ReplayError("Unexpected side-effect function '%s'"
                                  % name)
            exp_name, exp_args, exp_kwargs, result = side_effects.pop(0)
            if exp_name != name:
                raise ReplayError("Unexpected side-effect function '%s' "
                                  "instead of '%s'" % (name, exp_name))
            if exp_args != (args or None):
                raise ReplayError("Unexpected side-effect arguments %r "
                                  "instead of %r" % (args or None, exp_args))
            if exp_kwargs != (kwargs or None):
                raise ReplayError("Unexpected side-effect keywords %r instead "
                                  "of %r" % (kwargs or None, exp_kwargs))
            return section.exit(result)

        # We are not inside a recorded section, abort and execute
        section.abort()
        return check_result(callable(*args, **kwargs), name)

    return wrapper


class RecorderRoot(serialization.Serializable):

    implements(IRecorderNode)

    journal_parent = None

    def __init__(self, keeper, base_id=None):
        self.journal_keeper = IJournalKeeper(keeper)
        self._base_id = base_id and (base_id, ) or ()
        self._recorder_count = 0

    ### ISerializable Methods ###

    def recover(self, state):
        keeper, base, count = state
        self.journal_keeper = keeper
        self._base_id = base
        self._recorder_count = count

    def snapshot(self):
        return self.journal_keeper, self._base_id, self._recorder_count

    ### IRecorderNode Methods ###

    def generate_identifier(self, recorder):
        self._recorder_count += 1
        return self._base_id + (self._recorder_count, )


class RecorderNode(serialization.Serializable):

    implements(IRecorderNode)

    def __init__(self, parent):
        node = IRecorderNode(parent)
        identifier = node.generate_identifier(self)
        self.journal_parent = node
        self.journal_id = identifier
        self.journal_keeper = node.journal_keeper
        self._recorder_count = 0

    ### ISerializable Methods ###

    def recover(self, state):
        parent, keeper, ident, count = state
        self.journal_parent = parent
        self.journal_keeper = keeper
        self.journal_id = ident
        self._recorder_count = count

    def snapshot(self):
        return (self.journal_parent, self.journal_keeper,
                self.journal_id, self._recorder_count)

    ### IRecorderNode Methods ###

    def generate_identifier(self, recorder):
        self._recorder_count += 1
        return self.journal_id + (self._recorder_count, )


class Recorder(RecorderNode, annotate.Annotable):

    # Fix the metaclass inheritance
    __metaclass__ = type("MetaRecorder", (MetaAnnotable, MetaSerializable), {})

    implements(IRecorder)

    _registry = None

    @classmethod
    def _register_recorded_call(cls, function, custom_id=None):
        global _registry, _reverse

        if custom_id is not None:
            fun_id = custom_id
        else:
            parts = [cls.__module__, cls.__name__, function.__name__]
            fun_id = ".".join(parts)

        if fun_id in _registry:
            raise RuntimeError("Failed to register function %r with name '%s' "
                               "it is already used by function %r"
                               % (function, fun_id, _registry[fun_id]))

        _registry[fun_id] = function
        _reverse[function] = fun_id

    def __init__(self, parent):
        RecorderNode.__init__(self, parent)
        self.journal_keeper.register(self)

    ### IRecorder Methods ###

    def record(self, fun_id, args=None, kwargs=None, reentrant=True):
        return self._record(fun_id, None, args or (), kwargs or {},
                            reentrant=reentrant)

    def call(self, function, args=None, kwargs=None, reentrant=True):
        return self._record(None, function, args or (), kwargs or {},
                            reentrant=reentrant)

    def replay(self, fun_id, input):
        args, kwargs = input
        return self._replay(fun_id, None, args or (), kwargs or {})

    ### Private Methods ###

    def _record(self, fun_id, function, args, kwargs, reentrant=True):
        # Starts the fiber section
        section = fiber.WovenSection()
        section.enter()
        side_effects = None

        # Check if this is the first recording in the fiber section
        journal_mode = section.state.get(RECORDED_TAG, None)
        section_first = journal_mode is None
        fiber_first = section_first and section.descriptor.fiber_depth == 0

        if section_first:
            section.state[RECORDED_TAG] = JournalMode.recording
            side_effects = []
            section.state[SIDE_EFFECTS_TAG] = side_effects

        if not (fiber_first or reentrant):
            # If not reentrant and it is not the first, it's BAAAAAD.
            raise ReentrantCallError("Recorded functions cannot be called "
                                     "from another recorded function")

        fun_id, fun, result = self._call_fun(fun_id, function, args, kwargs)

        # If it is the first recording entry in the stack, add a journal entry
        if section_first:
            desc = section.descriptor
            self.journal_keeper.write_entry(self.journal_id, fun_id,
                                            desc.fiber_id, desc.fiber_depth,
                                            (args or None, kwargs or None),
                                            side_effects or None, result)

        return section.exit(result)

    def _replay(self, fun_id, function, args, kwargs):
        # Starts the fiber section
        section = fiber.WovenSection()
        section.enter()
        side_effects = None

        # Check if this is the first recording in the fiber section
        journal_mode = section.state.get(RECORDED_TAG, None)
        is_first = journal_mode is None

        if is_first:
            section.state[RECORDED_TAG] = JournalMode.replay
            side_effects = []
            section.state[SIDE_EFFECTS_TAG] = side_effects

        _, _, result = self._call_fun(fun_id, function, args, kwargs)

        # We don't want anything asynchronous to be called,
        # so we abort the fiber section
        section.abort(result)

        # We return the side effects and the result
        return side_effects or None, result

    def _call_fun(self, fun_id, function, args, kwargs):
        global _registry, _reverse

        if function is None:
            # Retrieve the function from the registry
            function = _registry.get(fun_id)
            if function is None:
                raise AttributeError("No registered function found with "
                                     "identifier '%s' to call with %r"
                                     % (fun_id, self))

        if fun_id is None:
            # Retrieve the identifier from the registry
            fun_id = _reverse.get(function)
            if fun_id is None:
                raise AttributeError("Function not register as recorded %r"
                                     % (function, ))

        # Call the function
        result = function(self, *args, **kwargs)

        # Check the function result. Deferred are not allowed because
        # it would mean an asynchronous call chain is already started.
        if isinstance(result, defer.Deferred):
            raise RecordingResultError("Recorded functions %s "
                                       "cannot return Deferred" % fun_id)

        return fun_id, function, result


class InMemoryJournalKeeper(object):
    '''Dummy in-memory journal keeper, DO NOT USE for serious stuff.'''

    implements(IJournalKeeper)

    def __init__(self):
        self.clear()

    def get_records(self):
        return self._records

    def clear(self):
        self._records = []
        self._registry = weakref.WeakValueDictionary()

    def lookup(self, journal_id):
        return self._registry.get(journal_id)

    def iter_recorders(self):
        return self._registry.itervalues()

    ### IJournalKeeper Methods ###

    def register(self, recorder):
        recorder = IRecorder(recorder)
        self._registry[recorder.journal_id] = recorder

    def write_entry(self, instance_id, entry_id,
                    fiber_id, fiber_depth, input, side_effects, output):
        record = (instance_id, entry_id, fiber_id, fiber_depth,
                  ISnapshotable(input).snapshot(),
                  ISnapshotable(side_effects).snapshot(),
                  ISnapshotable(output).snapshot())
        self._records.append(record)


### Private Stuff ###

_registry = {} # {FUNCTION_ID: FUNCTION}
_reverse = {} # {FUNCTION: FUNCTION_ID}
