from zope.interface import Interface, implements

from feat.common import (annotate, decorator, fiber, defer,
                         error_handler, serialization, )
from feat.agents.base import replay, message, requester, replier


class IRPCClient(Interface):

    def call_remote(recipient, fun_id, *args, **kwargs):
        pass


class IRPCServer(Interface):

    def call_local(fun_id, *args, **kwargs):
        pass


class RPCException(Exception):
    pass


class NotPublishedError(RPCException):
    pass


@decorator.simple_function
def publish(function):
    annotate.injectClassCallback("publish", 4, "_register_published", function)
    return function


class AgentMixin(object):

    implements(IRPCClient, IRPCServer)

    _published = None

    @replay.immutable
    def initiate(self, state):
        state.medium.register_interest(RPCReplier)


    ### IRPCClient Methods ###

    @replay.journaled
    def call_remote(self, state, recipient, fun_id, *args, **kwargs):
        timeout = kwargs.pop('_timeout', 10)
        f = fiber.Fiber()
        f.add_callback(self.initiate_protocol,
                       recipient, fun_id, *args, **kwargs)
        f.add_callback(RPCRequester.notify_finish)
        return f.succeed(RPCRequesterFactory(timeout))

    ### IRPCServer Methods ###

    def call_local(self, fun_id, *args, **kwargs):
        if not fun_id in self._published:
            raise NotPublishedError("Agent %s do not have any published "
                                    "function named '%s'"
                                    % (type(self).__name__, fun_id))
        value = self._published[fun_id](self, *args, **kwargs)
        return value

    ### Private Methods ###

    @classmethod
    def _register_published(cls, function):
        fun_id = function.__name__
        if cls._published is None:
            cls._published = {}
        cls._published[fun_id] = function


@serialization.register
class RPCRequesterFactory(serialization.Serializable):
    implements(requester.IRequesterFactory)

    protocol_type = 'Request'
    protocol_id = 'rpc'

    def __init__(self, timeout):
        self.timeout = timeout
        self.protocol_id = RPCRequester.protocol_id

    def __call__(self, agent, medium):
        instance = RPCRequester(agent, medium)
        instance.timeout = self.timeout
        return instance


class RPCRequester(requester.BaseRequester):

    protocol_id = 'rpc'

    def init_state(self, state, agent, med):
        requester.BaseRequester.init_state(self, state, IRPCClient(agent), med)

    @replay.entry_point
    def initiate(self, state, fun_id, *args, **kwargs):
        msg = message.RequestMessage()
        msg.payload['fun_id'] = fun_id
        msg.payload['args'] = args
        msg.payload['kwargs'] = kwargs
        state.medium.request(msg)

    def got_reply(self, reply):
        if reply.payload['succeed']:
            return reply.payload['result']
        exc = reply.payload['exception']
        msg = reply.payload['message']
        if issubclass(exc, RPCException):
            return defer.fail(exc(msg))
        return defer.fail(exc("REMOTE: " + str(msg)))


class RPCReplier(replier.BaseReplier):

    protocol_id = 'rpc'

    def init_state(self, state, agent, medium):
        replier.BaseReplier.init_state(self, state, IRPCServer(agent), medium)

    @replay.entry_point
    def requested(self, state, request):
        fun_id = request.payload['fun_id']
        args = request.payload['args']
        kwargs = request.payload['kwargs']
        f = fiber.succeed(fun_id)
        f.add_callback(state.agent.call_local, *args, **kwargs)
        f.add_callbacks(callback=self.got_result, errback=self.got_failure)
        return f

    @replay.journaled
    def got_result(self, state, result):
        msg = message.ResponseMessage()
        msg.payload['succeed'] = True
        msg.payload['result'] = result
        state.medium.reply(msg)

    @replay.immutable
    def got_failure(self, state, failure):
        error_handler(self, failure)
        msg = message.ResponseMessage()
        msg.payload['succeed'] = False
        msg.payload['exception'] = type(failure.value)
        msg.payload['message'] = failure.getErrorMessage()
        state.medium.reply(msg)
