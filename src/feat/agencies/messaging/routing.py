import operator

from zope.interface import implements

from feat.agencies.message import BaseMessage

from feat.common import log, container, time

from feat.agencies.messaging.interface import ISink
from feat.interface.generic import ITimeProvider


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

    def copy(self, **params):
        '''Creates the new instance of the Route substituting the requested
        parameters.'''
        new_params = dict()
        for name in ['owner', 'priority', 'key', 'final']:
            new_params[name] = params.get(name, getattr(self, name))
        return Route(**new_params)

    def match(self, message):
        if not isinstance(message, BaseMessage):
            raise AttributeError("Expected BaseMessage got %r" % (message, ))
        msg_key = (message.recipient.key, message.recipient.route)
        return msg_key == self.key

    def __repr__(self):
        return ("<Route: key=%s, priority=%d, final=%r, sink=%s>" %
                (self.key, self.priority, self.final,
                 type(self.owner).__name__))

    def __eq__(self, other):
        if not isinstance(other, type(self)):
            return NotImplemented
        return self.owner == other.owner and \
               self.priority == other.priority and \
               self.key == other.key and \
               self.final == other.final

    def __ne__(self, other):
        if not isinstance(other, type(self)):
            return NotImplemented
        return not self.__eq__(other)


class Table(log.Logger):

    implements(ITimeProvider)

    def __init__(self, logger, time_provider=None):
        log.Logger.__init__(self, logger)

        self._routes = list()
        self._outgoing_sink = None

        self._time_provider = time_provider and ITimeProvider(time_provider)

        self._message_store = MessageStore(self)

    ### ITimeProvider ###

    def get_time(self):
        return self._time_provider and self._time_provider.get_time() or \
               time.time()

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

        to_deliver = self._message_store.match_to_route(route)
        for message in to_deliver:
                self._send_to_route(message, route)

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

        if self._outgoing_sink == sink:
            self.info("Outgoing sink removed, setting to None.")
            self._outgoing_sink = None

    def dispatch(self, message, outgoing=True):

        for route in self._routes:
            self.log("Analizing route %r, matching=%r", route,
                     route.match(message))
            if route.match(message):
                self._send_to_route(message, route)
                if route.final:
                    return

        self._message_store.insert(message)

        if outgoing and self._outgoing_sink:
            self.log('Routing to default sink: %r', self._outgoing_sink)
            message = message.clone()
            self._outgoing_sink.on_message(message)

    ### private ###

    def _fix_order(self):
        self._routes = sorted(self._routes,
                              key=operator.attrgetter('priority'))

    def _send_to_route(self, message, route):
        message = message.clone()
        route.owner.on_message(message)


class MessageStore(object):
    """
    I'm a class responsible for holding the message until they expiration
    time and match them to correct routes.
    """

    def __init__(self, time_provider):
        self._store = container.ExpDict(time_provider)

    def insert(self, message):
        if not isinstance(message, BaseMessage):
            raise TypeError('Expected BaseMessage got %r' % (message, ))

        # ignore messages without expiration time (would leak)
        if message.expiration_time is not None:
            self._store.set(message.message_id, message,
                            message.expiration_time)

    def remove(self, message):
        if not isinstance(message, BaseMessage):
            raise TypeError('Expected BaseMessage got %r' % (message, ))

        self._store.pop(message.message_id, None)

    def match_to_route(self, route):
        if not isinstance(route, Route):
            raise TypeError('Expected Route got %r' % (route, ))

        matching = [x for x in self._store.itervalues() if route.match(x)]
        if route.final:
            [self.remove(x) for x in matching]
        return matching
