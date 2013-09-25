import sys
import os
import tempfile
import optparse
import ConfigParser
from StringIO import StringIO

from feat.agents.dns import dns_agent
from feat.agencies.net import options, configfile
from feat.common.text_helper import format_block
from feat.test import common


class TestConfigFile(common.TestCase):

    def setUp(self):
        self.parser = optparse.OptionParser()
        options.add_options(self.parser)
        self.parser.parse_args(args=[])

    def testStaticOptions(self):
        test_config = format_block("""
        [agency]
        journal: postgres://feat:feat@localhost/feat \
                 sqlite:///var/log/feat/journal.sqlite.3
        unix: /tmp/feat.socket
        rundir: /var/run/feat
        logdir: /var/log/feat
        lock: /tmp/feat.lock
        hostname: encoder001
        domainname: test.cluster.lan

        [rabbitmq]
        host: msg.test.cluster.lan
        port: 5842
        user: feat
        password: feat

        [tunneling]
        host: encoder001.test.cluster.lan
        port: 90000
        p12_path: /etc/ssl/cert/tunnel.p12

        [couchdb]
        host: couchdb.test.cluster.lan
        port: 5895
        name: feat

        [manhole]
        public_key: /etc/ssl/ssh/public_key
        private_key: /etc/ssl/ssh/private_key
        authorized_keys: /etc/ssl/ssh/authorized_keys
        port: 6000

        [gateway]
        port: 5200
        p12_path: /etc/ssl/cert/gateway.p12

        [host]
        resource: epu:1000 bandwidth:100
        ports: dns:10000:10001
        category: address:fixed storage:static

        [nagios]
        monitor: some.monitor.com
        monitor2: other.monitor.com
        """)

        f = StringIO(test_config)
        configfile.parse_file(self.parser, f)

        v = self.parser.values

        self.assertEqual(["postgres://feat:feat@localhost/feat",
                          "sqlite:///var/log/feat/journal.sqlite.3"],
                         v.agency_journal)
        self.assertEqual("/tmp/feat.socket", v.agency_socket_path)
        self.assertEqual("/var/run/feat", v.agency_rundir)
        self.assertEqual("/var/log/feat", v.agency_logdir)
        self.assertEqual('/tmp/feat.lock', v.lock_path)
        self.assertEqual('encoder001', v.agency_hostname)
        self.assertEqual('test.cluster.lan', v.agency_domainname)

        self.assertEqual('msg.test.cluster.lan', v.msg_host)
        self.assertEqual(5842, v.msg_port)
        self.assertEqual('feat', v.msg_user)
        self.assertEqual('feat', v.msg_password)

        self.assertEqual('encoder001.test.cluster.lan', v.tunnel_host)
        self.assertEqual(90000, v.tunnel_port)
        self.assertEqual("/etc/ssl/cert/tunnel.p12", v.tunnel_p12)

        self.assertEqual('couchdb.test.cluster.lan', v.db_host)
        self.assertEqual(5895, v.db_port)
        self.assertEqual("feat", v.db_name)

        self.assertEqual('/etc/ssl/ssh/public_key', v.manhole_public_key)
        self.assertEqual('/etc/ssl/ssh/private_key', v.manhole_private_key)
        self.assertEqual('/etc/ssl/ssh/authorized_keys',
                         v.manhole_authorized_keys)
        self.assertEqual(6000,
                         v.manhole_port)

        self.assertEqual(5200, v.gateway_port)
        self.assertEqual("/etc/ssl/cert/gateway.p12", v.gateway_p12)

        self.assertEqual(None, v.hostdef)
        self.assertEqual(['epu:1000', 'bandwidth:100'],
                         v.hostres)
        self.assertEqual(['dns:10000:10001'], v.hostports)
        self.assertEqual(['address:fixed', 'storage:static'], v.hostcat)

        self.assertEqual(['some.monitor.com', 'other.monitor.com'],
                         v.nagios_monitors)

    def testInclude(self):
        tmpfile = tempfile.mktemp()
        included = format_block("""
        [manhole]
        public_key: /etc/ssl/ssh/public_key
        private_key: /etc/ssl/ssh/private_key
        authorized_keys: /etc/ssl/ssh/authorized_keys
        port: 6000
        """)
        self.addCleanup(os.remove, tmpfile)
        with file(tmpfile, 'w') as f:
            f.write(included)

        test_config = format_block("""
        [include]
        to_include: %s""" % (tmpfile, ))
        f = StringIO(test_config)
        configfile.parse_file(self.parser, f)

        v = self.parser.values

        self.assertEqual('/etc/ssl/ssh/public_key', v.manhole_public_key)
        self.assertEqual('/etc/ssl/ssh/private_key', v.manhole_private_key)
        self.assertEqual('/etc/ssl/ssh/authorized_keys',
                         v.manhole_authorized_keys)
        self.assertEqual(6000,
                         v.manhole_port)

    def testParsingApplication(self):
        if 'feat.everything' in sys.modules:
            del(sys.modules['feat.everything'])
        test_config = format_block("""
        [application:feat]
        import: feat.agents.application
        name: feat""")
        f = StringIO(test_config)
        configfile.parse_file(self.parser, f)
        self.assertIn('feat.agents.application', sys.modules)

    def testParsingAgent(self):
        test_config = format_block("""
        [application:feat]
        import: feat.agents.application
        name: feat

        [agent:dns_0]
        agent_type: dns_agent
        descriptor.suffix: "test.lan"
        initiate.slaves: [["1.2.3.4", 53], ["5.6.7.8", 1000]]""")

        f = StringIO(test_config)
        configfile.parse_file(self.parser, f)

        v = self.parser.values
        self.assertEqual(1, len(v.agents))
        d = v.agents[0][0]
        self.assertIsInstance(d, dns_agent.Descriptor)
        self.assertIsInstance(d.suffix, unicode)
        self.assertEqual('test.lan', d.suffix)
        i = v.agents[0][1]
        self.assertIsInstance(i, dict)
        self.assertIn('slaves', i)
        self.assertEqual([["1.2.3.4", 53], ["5.6.7.8", 1000]], i['slaves'])
        self.assertEquals('dns_0', v.agents[0][2])

    def testUnknownAgentType(self):
        test_config = format_block("""
        [agent:dns_0]
        agent_type: unknown_agent
        descriptor.suffix: "test.lan"
        """)

        f = StringIO(test_config)
        self.assertRaises(ConfigParser.Error,
                          configfile.parse_file, self.parser, f)

    def testImportWrongModule(self):
        test_config = format_block("""
        [application:broken]
        import: not.existing.module
        """)
        f = StringIO(test_config)

        self.assertRaises(ConfigParser.Error,
                          configfile.parse_file, self.parser, f)
