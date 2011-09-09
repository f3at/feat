from zope.interface import implements

from feat.agencies import common, tunneling
from feat.agencies.tunneling import Channel, CHANNEL_TYPE
from feat.common import log, time
from feat.web import tunnel

from feat.interface.channels import IBackend
from feat.interface.recipient import IRecipients, RecipientType


class Backend(log.LogProxy, log.Logger, common.ConnectionManager):

    implements(IBackend, tunnel.ITunnelDispatcher)

    log_category = "tunneling"

    channel_type = CHANNEL_TYPE

    def __init__(self, host, port_range, version=None, registry=None):
        log.LogProxy.__init__(self, log.FluLogKeeper())
        log.Logger.__init__(self, self)
        common.ConnectionManager.__init__(self)

        self._pending_dispatches = 0
        self._channels = {} # {CHANNEL_ID: Channel}

        self._tunnel = tunnel.Tunnel(self, port_range, self, public_host=host,
                                     version=version, registry=registry)
        self._tunnel.start_listening()
        self._route = self._tunnel.uri
        self.info("Listening for tunneling connections on %s", self._route)
        self._on_connected()

    ### public ###

    @property
    def version(self):
        return self._version

    @property
    def route(self):
        return self._route

    def post(self, recipients, message):
        for recip in IRecipients(recipients):
            assert recip.channel == self.channel_type, \
                   "Unexpected channel type"
            if recip.type == RecipientType.broadcast:
                self.warning("Tunneling does not support broadcast "
                             "recipients, dropping message for %r", recip)
                continue
            self._post_message(recip, message)

    ### IBackend ###

    def is_idle(self):
        return self._pending_dispatches == 0 and self._tunnel.is_idle()

    # is_disconnected() from common.ConnectionManager

    # wait_connected() from common.ConnectionManager

    def disconnect(self):
        self._tunnel.stop_listening()
        self._tunnel.disconnect()

    def new_channel(self, agent):
        channel = Channel(self, agent)
        return channel.initiate()

    # add_disconnected_cb() from common.ConnectionManager

    # add_reconnected_cb() from common.ConnectionManager

    ### tunnel.ITunnelDispatcher ###

    def dispatch(self, uri, data):
        recip = tunneling.parse(uri)
        if recip.key not in self._channels:
            self.warning("Dropping message to unknown recipient %s", recip)
            return
        self._pending_dispatches += 1
        time.call_next(self._dispatch_message, recip, data)

    ### protected ###

    def _register_channel(self, channel):
        channel_id = channel.channel_id
        assert channel_id not in self._channels, \
               "Channel already registered"
        self._channels[channel_id] = channel

    def _release_channel(self, channel):
        channel_id = channel.channel_id
        assert channel_id in self._channels, \
               "Releasing unknown channel"
        del self._channels[channel_id]

    ### private ###

    def _post_message(self, recip, message):
        uri = tunneling.compose(recip)
        return self._tunnel.post(uri, message)

    def _dispatch_message(self, recip, message):
        self._pending_dispatches -= 1
        self._channels[recip.key]._dispatch(message)
