from zope.interface import implements

from feat.agencies import common
from feat.agencies.tunneling import Channel
from feat.common import log, time

from feat.interface.channels import IBackend
from feat.interface.recipient import IRecipients, RecipientType


class Backend(common.ConnectionManager, log.Logger, log.FluLogKeeper):

    implements(IBackend)

    log_category = "emu-tunneling"

    channel_type = "tunnel"

    def __init__(self):
        common.ConnectionManager.__init__(self)
        log.FluLogKeeper.__init__(self)
        log.Logger.__init__(self, self)

        self._channels = {} # {CHANNEL_ID: Channel}
        self._pending_count = 0

        self._on_connected()

    ### public ###

    def get_route(self):
        return "emu"

    def post(self, recipients, message):
        for recip in IRecipients(recipients):
            assert recip.channel == self.channel_type, \
                   "Unexpected channel type"
            assert recip.route == "emu", "Unexpected recipient route"
            if recip.type == RecipientType.broadcast:
                self.warning("Tunneling does not support broadcast "
                             "recipients, dropping message for %r", recip)
                continue
            self._pending_count += 1
            time.call_next(self._dispatch_message, recip, message)

    ### IBackend ###

    def is_idle(self):
        return self._pending_count == 0

    # is_disconnected() from common.ConnectionManager

    # wait_connected() from common.ConnectionManager

    def disconnect(self):
        pass

    def new_channel(self, agent):
        channel = Channel(self, agent)
        return channel.initiate()

    # add_disconnected_cb() from common.ConnectionManager

    # add_reconnected_cb() from common.ConnectionManager

    ### protected ###

    def _register_channel(self, channel_id, channel):
        assert channel_id not in self._channels, \
               "Channel already registered"
        self._channels[channel_id] = channel

    def _release_channel(self, channel_id):
        assert channel_id in self._channels, \
               "Releasing unknown channel"
        del self._channels[channel_id]

    ### private ###

    def _dispatch_message(self, recip, message):
        self._pending_count -= 1
        if recip.key not in self._channels:
            self.warning("Dropping message to unknown recipient %r", recip)
            return
        self._channels[recip.key]._dispatch(message)
