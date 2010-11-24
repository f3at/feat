from twisted.internet import defer
from zope.interface import implements

from feat.interface.fiber import *
from feat.interface.journal import *
from feat.interface.serialization import *

from . import decorator, annotate, reflect, fiber, serialization

RECORDED_TAG = "__RECORDED__"
SIDE_EFFECTS_TAG = "__SIDE_EFFECTS__"
INSIDE_EFFECT_TAG = "__INSIDE_EFFECT__"


@decorator.parametrized_function
def recorded(function, custom_id=None, reentrant=True):
    '''MUST only be used only with method from child
    classes of L{{Recorder}}.'''
    fun_id = custom_id or function.__name__
    annotate.injectClassCallback("recorded", 4,
                                 "_register_recorded_call", fun_id, function)

    def wrapper(self, *args, **kwargs):
        recorder = IRecorder(self)
        return recorder.call(fun_id, args, kwargs, reentrant=reentrant)

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
    __metaclass__ = type("MetaRecorder", (annotate.MetaAnnotable,
                                          serialization.MetaSerializable), {})

    implements(IRecorder)

    _registry = None

    @classmethod
    def _register_recorded_call(cls, fun_id, function):
        # Lazy registry creation to prevent all sub-classes
        # from sharing the same dictionary
        if cls._registry is None:
            cls._registry = {}
        cls._registry[fun_id] = function

    def __init__(self, parent):
        RecorderNode.__init__(self, parent)
        self.journal_keeper.register(self)

    ### IRecorder Methods ###

    def call(self, fun_id, args=None, kwargs=None, reentrant=True):
        # Starts the fiber section
        section = fiber.WovenSection()
        section.enter()
        side_effects = None

        # Check if this is the first recording in the fiber section
        journal_mode = section.state.get(RECORDED_TAG, None)
        is_first = journal_mode is None

        if is_first:
            section.state[RECORDED_TAG] = JournalMode.recording
            side_effects = []
            section.state[SIDE_EFFECTS_TAG] = side_effects

        elif not reentrant:
            # If not reentrant and it is not the first, it's BAAAAAD.
            raise ReentrantCallError("Recorded functions %s "
                                     "cannot be called from another "
                                     "recorded function" % fun_id)


        result = self._call_fun_id(fun_id, args or (), kwargs or {})

        # If it is the first recording entry in the stack, add a journal entry
        if is_first:
            desc = section.descriptor
            self.journal_keeper.record(self.journal_id, fun_id,
                                   desc.fiber_id, desc.fiber_depth,
                                   (args or None, kwargs or None),
                                   side_effects or None, result)

        # Exit the fiber section
        return section.exit(result)

    def replay(self, fun_id, input):
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

        args, kwargs = input
        result = self._call_fun_id(fun_id, args or (), kwargs or {})

        # We don't want anything asynchronous to be called,
        # so we abort the fiber section
        section.abort(result)

        # We return the side effects and the result
        return side_effects or None, result

    ### Private Methods ###

    def _call_fun_id(self, fun_id, args, kwargs):

        # Retrieve the function from the registry
        function = self._registry.get(fun_id)
        if function is None:
            raise AttributeError("Object '%s' has no recorded function "
                                 "with identifier '%s'"
                                 % (type(self).__name__, fun_id))

        # Call the function
        result = function(self, *args, **kwargs)

        # Check the function result. Deferred are not allowed because
        # it would mean an asynchronous call chain is already started.
        if isinstance(result, defer.Deferred):
            raise RecordingResultError("Recorded functions %s "
                                       "cannot return Deferred" % fun_id)

        return result
