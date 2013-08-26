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
# -*- Mode: Python -*-
# vi:si:et:sw=4:sts=4:ts=4
import uuid
import os

from twisted.internet import defer

from feat.agencies.messaging import tunneling
from feat.agencies import message, recipient
from feat.common import serialization
from feat.web import security

from . import common


class StubChannel(object):

    def __init__(self, backend):
        self.backend = backend
        self.messages = list()
        self.recipient = recipient.dummy_agent()

        # recp -> uri
        self.routes = dict()

        self.backend.connect(self)
        self.backend.add_route(self.recipient, self.backend.route)

    def create_external_route(self, backend_id, uri=None, recipient=None):
        self.routes[recipient] = uri
        self.backend.add_route(recipient, uri)

    def _dispatch(self, msg):
        self.messages.append(msg)


class Versioned(message.Notification, serialization.VersionAdapter):

    __metaclass__ = type("MetaVersioned", (type(message.Notification),
                                           type(serialization.VersionAdapter)),
                         {})


class Notification1(Versioned):
    type_name = "dummy-notif"

    def __init__(self, *args, **kwargs):
        message.Notification.__init__(self, *args, **kwargs)
        if "value" not in self.payload:
            self.payload["value"] = "42"


class Notification2(Notification1):
    type_name = "dummy-notif"

    def __init__(self, *args, **kwargs):
        message.Notification.__init__(self, *args, **kwargs)
        if "value" not in self.payload:
            self.payload["value"] = 42

    @staticmethod
    def upgrade_to_2(snapshot):
        old_value = snapshot["payload"]["value"]
        snapshot["payload"]["value"] = int(old_value)
        return snapshot

    @staticmethod
    def downgrade_to_1(snapshot):
        old_value = snapshot["payload"]["value"]
        snapshot["payload"]["value"] = str(old_value)
        return snapshot


class TestMixin(object):

    @defer.inlineCallbacks
    def testSimplePostMessage(self):
        channel = StubChannel(self.backend1)

        msg = message.BaseMessage(payload='some message',
                                  recipient=channel.recipient)

        self.backend1.post(msg)

        yield self.wait_for_idle()

        self.assertEqual(1, len(channel.messages))
        self.assertEqual('some message', channel.messages[0].payload)

    @defer.inlineCallbacks
    def testDialog(self):
        channel1 = StubChannel(self.backend1)
        channel2 = StubChannel(self.backend2)

        self.backend1.add_route(channel2.recipient, self.backend2.route)
        self.backend2.add_route(channel1.recipient, self.backend1.route)

        msg1 = message.DialogMessage()
        msg1.payload = "spam"
        msg1.recipient = channel2.recipient

        self.backend1.post(msg1)

        yield self.wait_for_idle()

        self.assertEqual(len(channel2.messages), 1)
        msg1b = channel2.messages[0]
        self.assertEqual(msg1b.payload, "spam")

        msg2 = message.DialogMessage()
        msg2.payload = "bacon"
        msg2.recipient = channel1.recipient

        self.backend2.post(msg2)

        yield self.wait_for_idle()

        self.assertEqual(len(channel1.messages), 1)
        msg2b = channel1.messages[0]
        self.assertEqual(msg2b.payload, "bacon")

    @defer.inlineCallbacks
    def testConvertion(self):
        channel1 = StubChannel(self.backend1)
        channel2 = StubChannel(self.backend2)

        self.backend1.add_route(channel2.recipient, self.backend2.route)
        self.backend2.add_route(channel1.recipient, self.backend1.route)

        msg = Notification1()
        msg.payload["value"] = "33"
        msg.recipient = channel2.recipient

        self.backend1.post(msg)

        yield self.wait_for_idle()

        self.assertEqual(1, len(channel2.messages))
        self.assertEqual(channel2.messages[0].payload, {"value": 33})

        msg = Notification2()
        msg.payload["value"] = 66
        msg.recipient = channel1.recipient

        self.backend2.post(msg)

        yield self.wait_for_idle()

        self.assertEqual(1, len(channel1.messages))
        self.assertEqual(channel1.messages[0].payload, {"value": "66"})

    ### private ###

    def wait_for_idle(self):

        def check():
            return self.backend1.is_idle() and self.backend2.is_idle()

        return self.wait_for(check, 20)


class TestEmuTunneling(common.TestCase, TestMixin):

    timeout = 5

    def setUp(self):
        bridge = tunneling.Bridge()

        registry1 = serialization.get_registry().clone()
        registry1.register(Notification1)
        self.backend1 = tunneling.EmuBackend(version=1, bridge=bridge,
                                             registry=registry1)

        registry2 = serialization.get_registry().clone()
        registry2.register(Notification2)
        self.backend2 = tunneling.EmuBackend(version=2, bridge=bridge,
                                             registry=registry2)

        return common.TestCase.setUp(self)

    def tearDown(self):
        self.backend1.disconnect()
        self.backend2.disconnect()
        return common.TestCase.tearDown(self)


class TestNetTCPTunneling(common.TestCase, TestMixin):

    timeout = 5

    def setUp(self):
        port_range = range(4000, 4100)
        registry1 = serialization.get_registry().clone()
        registry1.register(Notification1)
        self.backend1 = tunneling.Backend("localhost",
                                              port_range=port_range,
                                              version=1, registry=registry1)

        registry2 = serialization.get_registry().clone()
        registry2.register(Notification2)
        self.backend2 = tunneling.Backend("localhost",
                                          port_range=port_range,
                                          version=2, registry=registry2)

        return common.TestCase.setUp(self)

    def tearDown(self):
        self.backend1.disconnect()
        self.backend2.disconnect()
        return common.TestCase.tearDown(self)


class TestNetSSLTunneling(common.TestCase, TestMixin):

    timeout = 5

    def setUp(self):
        root = os.path.join(os.path.dirname(__file__), "data")
        svr_key = os.path.join(root, "ca1_server1_key.pem")
        svr_cert = os.path.join(root, "ca1_server1_cert.pem")
        cli_key = os.path.join(root, "ca1_client1_key.pem")
        cli_cert = os.path.join(root, "ca1_client1_cert.pem")
        ca_certs = os.path.join(root, "ca1_certs.pem")

        svr_fac = security.ServerContextFactory(svr_key, svr_cert, ca_certs)
        svr_sec = security.ServerPolicy(svr_fac)
        cli_fac = security.ClientContextFactory(cli_key, cli_cert, ca_certs)
        cli_sec = security.ClientPolicy(cli_fac)

        port_range = range(4000, 4100)
        registry1 = serialization.get_registry().clone()
        registry1.register(Notification1)
        self.backend1 = tunneling.Backend("localhost",
                                          port_range=port_range,
                                          version=1, registry=registry1,
                                          server_security_policy=svr_sec,
                                          client_security_policy=cli_sec)

        registry2 = serialization.get_registry().clone()
        registry2.register(Notification2)
        self.backend2 = tunneling.Backend("localhost",
                                          port_range=port_range,
                                          version=2, registry=registry2,
                                          server_security_policy=svr_sec,
                                          client_security_policy=cli_sec)

        return common.TestCase.setUp(self)

    def tearDown(self):
        self.backend1.disconnect()
        self.backend2.disconnect()
        return common.TestCase.tearDown(self)


class TestNetSSLTunnelingWithPKCS12(common.TestCase, TestMixin):

    timeout = 5

    def setUp(self):
        root = os.path.join(os.path.dirname(__file__), "data")
        svr_p12 = os.path.join(root, "ca1_server1.p12")
        cli_p12 = os.path.join(root, "ca1_client1.p12")

        svr_fac = security.ServerContextFactory(p12_filename=svr_p12,
                                                verify_ca_from_p12=True)
        svr_sec = security.ServerPolicy(svr_fac)
        cli_fac = security.ClientContextFactory(p12_filename=cli_p12,
                                                verify_ca_from_p12=True)
        cli_sec = security.ClientPolicy(cli_fac)

        port_range = range(4000, 4100)
        registry1 = serialization.get_registry().clone()
        registry1.register(Notification1)
        self.backend1 = tunneling.Backend("localhost",
                                          port_range=port_range,
                                          version=1, registry=registry1,
                                          server_security_policy=svr_sec,
                                          client_security_policy=cli_sec)

        registry2 = serialization.get_registry().clone()
        registry2.register(Notification2)
        self.backend2 = tunneling.Backend("localhost",
                                          port_range=port_range,
                                          version=2, registry=registry2,
                                          server_security_policy=svr_sec,
                                          client_security_policy=cli_sec)

        return common.TestCase.setUp(self)

    def tearDown(self):
        self.backend1.disconnect()
        self.backend2.disconnect()
        return common.TestCase.tearDown(self)
