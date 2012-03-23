import optparse

from feat.test import common
from feat.agencies.net import config, options


class OptParseMock(object):
    msg_port = '1999'
    manhole_public_key = 'file2'
    agent_name = 'name'


class UnitTestCase(common.TestCase):

    def setUp(self):
        common.TestCase.setUp(self)
        self.config = config.Config()

    def testOtherEnvironmentVariables(self):
        # this test checks the problem we had after indroducing other
        # environment variable starting with FEAT_ is fixed
        env = {
            'FEAT_TEST_PG_NAME': 'feat_test',
            }
        self.config.load(env) #no exception

    def testLoadConfig(self):
        env = {
            'FEAT_MSG_PORT': '2000',
            'FEAT_MANHOLE_PUBLIC_KEY': '"file"',
            'FEAT_AGENCY_JOURNAL':
            '["postgres://localhost/feat", "sqlite://journaler.sqlite3"]'}

        self.config.load(env)
        self.assertEqual(2000, self.config.msg.port)
        self.assertEqual('file', self.config.manhole.public_key)
        j = self.config.agency.journal
        self.assertIsInstance(j, list)
        self.assertEqual('postgres://localhost/feat', j[0])
        self.assertEqual('sqlite://journaler.sqlite3', j[1])

        #Overwrite some configuration values
        self.config.load(env, OptParseMock())
        self.assertEqual('1999', self.config.msg.port)
        self.assertEqual('file2', self.config.manhole.public_key)

    def testStoreConfig(self):
        self.config.msg.port = 3000
        self.config.msg.host = 'localhost'
        self.config.manhole.public_key = 'file'
        self.config.agency.journal = ['postgres://localhost/feat',
                                      'sqlite://journaler.sqlite3']
        env = dict()
        self.config.store(env)
        self.assertEqual('"localhost"', env['FEAT_MSG_HOST'])
        self.assertEqual('3000', env['FEAT_MSG_PORT'])
        self.assertEqual('"file"', env['FEAT_MANHOLE_PUBLIC_KEY'])
        exp = '["postgres://localhost/feat", "sqlite://journaler.sqlite3"]'
        self.assertEqual(exp, env['FEAT_AGENCY_JOURNAL'])

    def testDefaultConfig(self):
        parser = optparse.OptionParser()
        options.add_options(parser)
        defaults = parser.get_default_values()
        self.assertTrue(hasattr(defaults, 'msg_host'))
        self.assertTrue(hasattr(defaults, 'msg_port'))
        self.assertTrue(hasattr(defaults, 'msg_user'))
        self.assertTrue(hasattr(defaults, 'msg_password'))
        self.assertTrue(hasattr(defaults, 'db_host'))
        self.assertTrue(hasattr(defaults, 'db_port'))
        self.assertTrue(hasattr(defaults, 'db_name'))
        self.assertTrue(hasattr(defaults, 'manhole_public_key'))
        self.assertTrue(hasattr(defaults, 'manhole_private_key'))
        self.assertTrue(hasattr(defaults, 'manhole_authorized_keys'))
        self.assertTrue(hasattr(defaults, 'manhole_port'))
        self.assertEqual(self.config.msg.host,
                         options.DEFAULT_MSG_HOST)
        self.assertEqual(self.config.msg.port,
                         options.DEFAULT_MSG_PORT)
        self.assertEqual(self.config.msg.user,
                         options.DEFAULT_MSG_USER)
        self.assertEqual(self.config.msg.password,
                         options.DEFAULT_MSG_PASSWORD)
        self.assertEqual(self.config.db.host,
                         options.DEFAULT_DB_HOST)
        self.assertEqual(self.config.db.port,
                         options.DEFAULT_DB_PORT)
        self.assertEqual(self.config.db.name,
                         options.DEFAULT_DB_NAME)
        self.assertEqual(self.config.manhole.public_key,
                         options.DEFAULT_MH_PUBKEY)
        self.assertEqual(self.config.manhole.private_key,
                         options.DEFAULT_MH_PRIVKEY)
        self.assertEqual(self.config.manhole.authorized_keys,
                         options.DEFAULT_MH_AUTH)
        self.assertEqual(self.config.manhole.port,
                         options.DEFAULT_MH_PORT)
