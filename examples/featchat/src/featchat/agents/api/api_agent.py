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

from feat.common import fiber, defer
from feat.agencies import recipient, document
from feat.agents.base import agent, dependency, replay, view, alert
from feat.agents.common import dns, monitor, start_agent

from feat.interface.agency import ExecMode
from featchat.agents.api.interface import IWebAgent, IServerFactory
from featchat.agents.common import room
from featchat.application import featchat


DEFAULT_PORT = 8880
DEFAULT_DNS_PREFIX = u'api'


@featchat.register_restorator
class ApiAgentConfiguration(document.Document):

    type_name = 'api_agent_conf'
    document.field('doc_id', u'api_agent_conf', '_id')
    document.field('dns_prefix', DEFAULT_DNS_PREFIX)
    document.field('port', DEFAULT_PORT)

featchat.initial_data(ApiAgentConfiguration)


@featchat.register_agent('api_agent')
class ApiAgent(agent.BaseAgent, alert.AgentMixin):
    implements(IWebAgent)

    restart_strategy = monitor.RestartStrategy.wherever

    dependency.register(IServerFactory,
                        'featchat.agents.api.web.ServerDummy',
                        ExecMode.test)
    dependency.register(IServerFactory,
                        'featchat.agents.api.web.ServerDummy',
                        ExecMode.simulation)
    dependency.register(IServerFactory,
                        'featchat.agents.api.web.ServerWrapper',
                        ExecMode.production)

    @replay.mutable
    def initiate(self, state, dns_prefix=None, port=None):
        config = state.medium.get_configuration()
        state.dns_prefix = dns_prefix or config.dns_prefix
        state.port = port or config.port
        self.debug('Initializing api agent with: port=%d, dns_prefix=%s',
                   state.port, state.dns_prefix)

        state.server = self.dependency(IServerFactory, self, state.port)
        state.server.start()

    @replay.mutable
    def startup(self, state):
        self.startup_monitoring()
        return self.register_dns_mapping()

    @replay.mutable
    def on_killed(self, state):
        self.info("Going to release the web server because we are dying")
        state.server.stop()

    @replay.mutable
    def shutdown(self, state):
        state.server.stop()
        return self.unregister_dns_mapping()

    ### DNS stuff ###

    @replay.mutable
    def register_dns_mapping(self, state):
        '''
        Registers to dns and stores the current address in descriptor.
        If we already have ip in descriptor, this means that we have been
        restarted. In this case we remove the old DNS entry.
        '''

        def update_ip(desc, ip):
            desc.ip = ip

        def dns_error(failure):
            self.raise_alert("Failed to register dns entry!",
                             alert.Severity.medium)
            self.error('Error registering dns entry. %r', failure)

        desc = self.get_descriptor()
        ip = state.medium.get_ip()

        f = fiber.succeed()
        if desc.ip is not None:
            self.info("Removing old dns mapping for ip: %s", desc.ip)
            f.add_callback(dns.remove_mapping, self, state.dns_prefix,
                           desc.ip)
            f.add_callback(fiber.drop_param, self.update_descriptor,
                           update_ip, None)
        f.add_callback(fiber.drop_param,
                       dns.add_mapping, self, state.dns_prefix, ip)
        f.add_callback(fiber.drop_param, self.update_descriptor,
                       update_ip, ip)
        f.add_errback(dns_error)
        return f

    @replay.mutable
    def unregister_dns_mapping(self, state):

        def dns_error(failure):
            self.error('Error unregistering dns entry. %r', failure)

        ip = state.medium.get_ip()
        config = state.medium.get_configuration()
        f = dns.remove_mapping(self, config.dns_prefix, ip)
        f.add_errback(dns_error)
        return f

    ### IWebAgent ###

    @replay.immutable
    def get_list_for_room(self, state, name):
        name = unicode(name)

        def analyze_result(result, name):
            if not result:
                raise ValueError("Room with name=%r not found" % (name, ))

            return room.get_room_list(self, result[0].recipient)

        d = state.medium.query_view(Rooms, key=name)
        d.addCallback(analyze_result, name)
        return d

    @replay.immutable
    def get_url_for_room(self, state, name):
        name = unicode(name)

        def analyze_result(result, name):
            if not result:
                desc = room.Descriptor(name=name)
                d = state.medium.save_document(desc)
                d.addCallback(defer.inject_param, 1,
                              state.medium.initiate_protocol,
                              start_agent.GloballyStartAgent)
                d.addCallback(defer.call_param, 'notify_finish')
            else:
                d = defer.succeed(result[0].recipient)
            d.addCallback(defer.inject_param, 1, room.get_join_url, self)
            return d

        d = state.medium.query_view(Rooms, key=name)
        d.addCallback(analyze_result, name)
        return d

    @replay.immutable
    def get_room_list(self, state):

        def format_resp(rooms):
            return [unicode(x.name) for x in rooms]

        d = state.medium.query_view(Rooms)
        d.addCallback(format_resp)
        return d

    ### endof IWebAgent


@featchat.register_view
class Rooms(view.FormatableView):

    name = 'rooms'
    view.field('name', None)
    view.field('key', None)
    view.field('shard', None)

    @property
    def recipient(self):
        if not hasattr(self, '_recipient'):
            self._recipient = recipient.Agent(self.key, self.shard)
        return self._recipient

    def map(doc):
        if doc['.type'] == 'room_agent':
            yield (unicode(doc['name']),
                   dict(name=doc['name'], key=doc['_id'], shard=doc['shard']))
