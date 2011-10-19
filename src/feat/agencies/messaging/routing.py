import operator

from feat.agents.base.message import BaseMessage

from feat.agencies.messaging.interface import ISink
from feat.interface.recipient import RecipientType

from feat.common import log


class Route(object):

    def __init__(self, owner, key=None, priority=0, final=True):
        # the reference to the ISink to which we give the message
        self.owner = ISink(owner)
        # priority in the routing table (lower is more importanat)
        self.priority = priority
        # key of the agent, tuple (key, shard)
        self.key = key
        # flag saying that if the route matches the processing should finish
        self.final = final

    def match(self, message):
        if not isinstance(message, BaseMessage):
            raise AttributeError("Expected BaseMessage got %r" % (message, ))
        msg_key = (message.recipient.key, message.recipient.route)
        return msg_key == self.key

    def __repr__(self):
        return ("<Route: key=%s, priority=%d, final=%r, sink=%s>" %
                (self.key, self.priority, self.final,
                 type(self.owner).__name__))


class Table(log.Logger):

    def __init__(self, logger):
        log.Logger.__init__(self, logger)

        self._routes = list()
        self._outgoing_sink = None

    ### public ###

    def set_outgoing_sink(self, sink):
        sink = ISink(sink)
        if self._outgoing_sink is not None:
            raise RuntimeError("set_outgoing_sink() called for the second "
                               "time. New value %r, old value %r" %
                               (sink, self._outgoing_sink, ))
        self._outgoing_sink = sink

    def append_route(self, route):
        if not isinstance(route, Route):
            raise AttributeError('Expected Route, got %r' % (route, ))
        if route.key is None:
            raise AttributeError('Routes in routing table need to '
                                 'have the key')
        self.log("Appending inbound route: %r", route)
        self._routes.append(route)
        self._fix_order()

    def remove_route(self, route):
        try:
            self._routes.remove(route)
        except ValueError:
            self.warning("Trying to remove nonexisting route: %r", route)

    def remove_sink(self, sink):
        for route in self._routes:
            if route.owner == sink:
                self.remove_route(route)

    def dispatch(self, message, outgoing=True):

        def do_route(message, route):
            message = message.clone()
            route.owner.on_message(message)

        for route in self._routes:
            self.log("Analizing route %r, matching=%r", route,
                     route.match(message))
            if route.match(message):
                do_route(message, route)
                if route.final:
                    return
        if outgoing and self._outgoing_sink:
            self.log('Routing to default sink: %r', self._outgoing_sink)
            message = message.clone()
            self._outgoing_sink.on_message(message)

    ### private ###

    def _fix_order(self):
        self._routes = sorted(self._routes,
                              key=operator.attrgetter('priority'))
