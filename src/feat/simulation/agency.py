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

    def __eq__(self, other):
        if not isinstance(other, type(self)):
            return NotImplemented
        return True

    def __ne__(self, other):
        if not isinstance(other, type(self)):
            return NotImplemented
        return False


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

    def initiate(self, messaging, database, journaler, driver):
        self._driver = driver
        return agency.Agency.initiate(self, messaging, database, journaler)

    def upgrade(self, upgrade_cmd):
        self._upgrade_cmd = upgrade_cmd
        return agency.Agency.upgrade(self, upgrade_cmd)

    def get_upgrade_command(self):
        '''
        Should be used only in tests for checking if the upgrade has been
        triggered correctly.
        '''
        if not hasattr(self, '_upgrade_cmd'):
            raise AssertationError('upgrade() has not been called for this'
                                   ' agency.')
        return self._upgrade_cmd

    def shutdown(self):
        d = agency.Agency.shutdown(self)
        if hasattr(self, '_driver'):
            d.addCallback(defer.drop_param, self._driver.remove_agency, self)
        return d
