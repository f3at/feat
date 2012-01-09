from feat.test import common
from feat.agents.dns import api


class TestSlavesValue(common.TestCase):

    def setUp(self):
        self.value = api.SlavesValue()

    def testValidate(self):
        self.assertRaises(ValueError, self.value.validate, None)
        self.assertRaises(ValueError, self.value.validate, '1.2.3.4.5:50')
        self.assertRaises(ValueError, self.value.validate, 'hostname:50')
        self.assertEquals([], self.value.validate(''))
        self.assertEquals([(u'1.2.3.4', 40)],
                          self.value.validate('1.2.3.4:40'))
        self.assertEquals([(u'1.2.3.4', 40), (u'1.2.3.5', 50)],
                          self.value.validate('1.2.3.4:40, 1.2.3.5:50'))
        self.assertEquals([(u'1.2.3.4', 40), (u'1.2.3.5', 53)],
                          self.value.validate('1.2.3.4:40, 1.2.3.5'))

    def testPublish(self):
        self.assertEquals('', self.value.publish([]))
        self.assertEquals('1.2.3.4:40',
                          self.value.publish([(u'1.2.3.4', 40)]))
        self.assertEquals('1.2.3.4:40, 1.2.3.5:50',
                          self.value.publish(
                              [(u'1.2.3.4', 40), (u'1.2.3.5', 50)]))
