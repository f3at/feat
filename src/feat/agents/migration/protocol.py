from twisted.python import failure

from feat.agents.base import requester, replier, replay, message
from feat.common import formatable, fiber, error_handler, serialization


class BaseCommand(formatable.Formatable):
    # FIXME: use versioned formatable when this is done

    response_factory = None

    formatable.field('method', None)


class BaseResponse(formatable.Formatable):
    # FIXME: use versioned formatable when this is done

    formatable.field('success', True)


@serialization.register
class FailResponse(BaseResponse):

    formatable.field('success', False)
    formatable.field('failure', None)


class Requester(requester.BaseRequester):

    timeout = 10

    protocol_id = "migration"

    @replay.entry_point
    def initiate(self, state, command):
        if not isinstance(command, BaseCommand):
            raise TypeError("Run it passing BaseCommand as the argument, "
                            "got %r instead." % command)
        state.command = command
        msg = message.RequestMessage(payload=command)
        state.medium.request(msg)

    @replay.journaled
    def got_reply(self, state, reply):
        assert isinstance(reply.payload, BaseResponse), reply.payload
        if reply.payload.success:
            return reply.payload
        else:
            return fiber.fail(reply.payload.failure)


class Replier(replier.BaseReplier):

    protocol_id = "migration"

    @replay.entry_point
    def requested(self, state, request):
        command = request.payload
        snapshot = command.snapshot()
        state.method = snapshot.pop('method')
        state.keywords = snapshot
        state.response_factory = command.response_factory

        self.log("Received request, method %r, keywords: %r",
                 state.method, state.keywords)
        f = fiber.succeed(canceller=state.medium.get_canceller())
        f.add_callback(fiber.drop_param, self._process)
        f.add_callback(self._send_reply)
        return f

    @replay.journaled
    def _process(self, state):
        method = getattr(state.agent, state.method, None)
        if not callable(method):
            raise ValueError("Agent doesn't have method %r." %
                             state.method)
        f = fiber.succeed()
        f.add_callback(fiber.drop_param, method, **state.keywords)
        f.add_callback(self._check_result)
        f.add_errback(self._error_handler)
        return f

    @replay.journaled
    def _check_result(self, state, result):
        expected_type = state.response_factory
        if not isinstance(result, expected_type):
            raise TypeError("Expected %s method to return value of type %r, "
                            "got %r instead." % (state.method,
                                                 expected_type,
                                                 result))
        return result

    def _error_handler(self, fail):
        error_handler(self, fail)
        return FailResponse(success=False, failure=fail)

    @replay.immutable
    def _send_reply(self, state, res):
        state.medium.reply(message.ResponseMessage(payload=res))
