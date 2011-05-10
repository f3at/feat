from zope.interface import implements

from feat.agencies import agency
from feat.agents.base import replay
from feat.common import serialization, manhole, defer, guard

from feat.interface.protocols import *


@serialization.register
class DummyInitiator(serialization.Serializable):

    implements(IInitiator)

    def __init__(self):
        self.state = guard.MutableState()
        self.state.medium = self

    def notify_finish(self):
        return defer.succeed(self)

    def is_idle(self):
        return True

    def _get_state(self):
        return self.state

    def expire_now(self):
        return defer.succeed(self)


class AgencyAgent(agency.AgencyAgent):

    ### Overridden Methods ###

    @serialization.freeze_tag('AgencyAgent.initiate_protocol')
    @replay.named_side_effect('AgencyAgent.initiate_protocol')
    def initiate_protocol(self, factory, *args, **kwargs):
        if not self.agency.is_protocol_disabled(factory):
            return agency.AgencyAgent.initiate_protocol(self, factory,
                                                        *args, **kwargs)
        dummy = DummyInitiator()
        dummy.protocol_type = factory.protocol_type
        dummy.protocol_id = factory.protocol_id
        return dummy


class Agency(agency.Agency):

    agency_agent_factory = AgencyAgent

    def __init__(self):
        agency.Agency.__init__(self)
        self._disabled_protocols = set()

    ### Public Methods ###

    def is_protocol_disabled(self, protocol_id, protocol_type=None):
        if protocol_id is None:
            return False

        if not isinstance(protocol_id, str):
            factory = IInitiatorFactory(protocol_id)
            protocol_id = factory.protocol_id
            assert protocol_type is None
            protocol_type = factory.protocol_type

        key = (protocol_id, protocol_type)
        return key in self._disabled_protocols

    @manhole.expose()
    def disable_protocol(self, protocol_id, protocol_type=None):
        if not isinstance(protocol_id, str):
            factory = IInitiatorFactory(protocol_id)
            protocol_id = factory.protocol_id
            assert protocol_type is None
            protocol_type = factory.protocol_type

        key = (protocol_id, protocol_type)
        self._disabled_protocols.add(key)

    @manhole.expose()
    def enable_protocol(self, protocol_id, protocol_type=None):
        if not isinstance(protocol_id, str):
            factory = IInitiatorFactory(protocol_id)
            protocol_id = factory.protocol_id
            assert protocol_type is None
            protocol_type = factory.protocol_type

        key = (protocol_id, protocol_type)
        if key in self._disabled_protocols:
            self._disabled_protocols.remove(key)
