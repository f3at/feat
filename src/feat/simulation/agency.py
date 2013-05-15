# F3AT - Flumotion Asynchronous Autonomous Agent Toolkit
# Copyright (C) 2010,2011 Flumotion Services, S.A.
# All rights reserved.

# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License along
# with this program; if not, write to the Free Software Foundation, Inc.,
# 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA.

# See "LICENSE.GPL" in the source distribution for more information.

# Headers in this file shall remain intact.
from zope.interface import implements

from feat.agencies import agency
from feat.agents.base import replay
from feat.common import serialization, manhole, defer, guard, formatable

from feat.interface.protocols import IInitiator, IInitiatorFactory


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

    def cleanup(self):
        return

    def __eq__(self, other):
        if not isinstance(other, type(self)):
            return NotImplemented
        return True

    def __ne__(self, other):
        if not isinstance(other, type(self)):
            return NotImplemented
        return False


@serialization.register
class DependencyReference(formatable.Formatable):

    formatable.field('agent_id', None)
    formatable.field('instance', None)
    formatable.field('component', None)
    formatable.field('mode', None)
    formatable.field('args', None)
    formatable.field('kwargs', None)


class AgencyAgent(agency.AgencyAgent):

    keeps_track_of_dependencies = True

    def register_dependency_reference(self, instance, component, mode,
                                      args, kwargs):
        a_id = self._descriptor.doc_id
        reference = DependencyReference(agent_id=a_id,
                                        instance=instance,
                                        component=component,
                                        mode=mode,
                                        args=args,
                                        kwargs=kwargs)
        if hasattr(instance, 'register_simulation_driver'):
            instance.register_simulation_driver(self.agency._driver)

        if not hasattr(self, '_dependency_references'):
            self._dependency_references = list()
        self._dependency_references.append(reference)

    def iter_dependency_references(self):
        if not hasattr(self, '_dependency_references'):
            return iter([])
        return iter(self._dependency_references)

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


class Shutdown(agency.Shutdown):

    def stage_process(self):
        self.friend._driver.remove_agency(self.friend)


class Startup(agency.Startup):

    def stage_configure(self):
        ip = self.opts.get('ip')
        if ip is not None:
            self.friend._ip = ip
        hostname = self.opts.get('hostname')
        if hostname is not None:
            self.friend._hostname = hostname


class Agency(agency.Agency):

    agency_agent_factory = AgencyAgent

    shutdown_factory = Shutdown
    startup_factory = Startup

    def __init__(self):
        agency.Agency.__init__(self)
        self._disabled_protocols = set()

        # config is used by some models, this is to be able to tests them
        self.config = dict()
        self.config['gateway'] = dict(port=5550)

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

    def initiate(self, database, journaler, driver, ip, hostname,
                 start_host, *backends):
        self._driver = driver
        d = self._initiate(database=database, journaler=journaler, ip=ip,
                           hostname=hostname, backends=backends)
        if start_host:
            d.addCallback(defer.drop_result, self._start_host_agent)
        return d

    def upgrade(self, upgrade_cmd):
        self._upgrade_cmd = upgrade_cmd
        return agency.Agency.upgrade(self, upgrade_cmd)

    def get_upgrade_command(self):
        '''
        Should be used only in tests for checking if the upgrade has been
        triggered correctly.
        '''
        if not hasattr(self, '_upgrade_cmd'):
            raise AssertionError('upgrade() has not been called for this'
                                   ' agency.')
        return self._upgrade_cmd

    def _get_host_agent_id(self):
        return self._driver.get_host_agent_id(
            agency.Agency._get_host_agent_id(self))
