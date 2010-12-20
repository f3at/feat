# -*- Mode: Python -*-
# vi:si:et:sw=4:sts=4:ts=4

from feat.test import common
from feat.simulation import driver


class IntegrationTest(common.TestCase):
    pass


class SimulationTest(common.TestCase):

    def setUp(self):
        self.driver = driver.Driver()
        return self.prolog()

    def process(self, script):
        d = self.cb_after(None, self.driver, 'finished_processing')
        self.driver.process(script)
        return d

    def get_local(self, name):
        return self.driver._parser.get_local(name)
