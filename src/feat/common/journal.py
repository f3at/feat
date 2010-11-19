from twisted.internet import defer
from zope.interface import implements

from feat.interface.fiber import *
from feat.interface.journal import *

from . import decorator, annotate, fiber

RECORDED_TAG = "__RECORDED__"
SIDE_EFFECTS_TAG = "__SIDE_EFFECTS__"


@decorator.parametrized_function
def recorded(function, custom_id=None, reentrant=True):
    fun_id = custom_id or function.__name__
    annotate.injectClassCallback("recorded", 4,
                                 "_register_recorded_call", fun_id, function)

    def wrapper(self, *args, **kwargs):
        recorder = IRecorder(self)
        return recorder.call(fun_id, args, kwargs, reentrant=reentrant)

    return wrapper


class RecorderRoot(object):

    implements(IRecorderNode)

    journal_parent = None

    def __init__(self, keeper, mode=JournalMode.recording, base_id=None):
        self.journal_keeper = IJournalKeeper(keeper)
        self.journal_mode = mode
        self._base_id = base_id and (base_id, ) or ()
        self._recorder_count = 0

    ### IRecorderNode Methods ###

    def generate_identifier(self, recorder):
        self._recorder_count += 1
        return self._base_id + (self._recorder_count, )


class RecorderNode(object):

    implements(IRecorderNode)

    def __init__(self, parent):
        node = IRecorderNode(parent)
        identifier = node.generate_identifier(self)
        self.journal_parent = node
        self.journal_id = identifier
        self.journal_keeper = node.journal_keeper
        self.journal_mode = node.journal_mode
        self._recorder_count = 0

    ### IRecorderNode Methods ###

    def generate_identifier(self, recorder):
        self._recorder_count += 1
        return self.journal_id + (self._recorder_count, )


class Recorder(RecorderNode, annotate.Annotable):

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
        is_first = not section.state.get(RECORDED_TAG, False)
        if not (is_first or reentrant):
            # If not reentrant and it is not the first, it's BAAAAAD.
            raise ReentrantCallError("Recorded functions %s "
                                     "cannot be called from another "
                                     "recorded function" % fun_id)

        if is_first:
            section.state[RECORDED_TAG] = True
            side_effects = []
            section.state[SIDE_EFFECTS_TAG] = side_effects

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

        is_first = not section.state.get(RECORDED_TAG, False)

        if is_first:
            section.state[RECORDED_TAG] = True
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


class FileJournalRecorder(object):

    implements(IJournalKeeper)

    ### IJournalKeeper Methods ###

    def register(self, recorder):
        '''No registration needed for recording.'''

    def record(self, instance_id, entry_id,
               fiber_id, fiber_depth, input, output):
        pass
