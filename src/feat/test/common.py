from feat.common import log
from feat.interface import logging
from twisted.trial import unittest
import sys

try:
    a = already_done
except NameError:
    sys.stderr = file('test.log', 'a')
    log.FluLogKeeper.init()
    already_done = True


class TestCase(unittest.TestCase, log.FluLogKeeper, log.Logger):

    log_category = "test"

    def __init__(self, *args, **kwargs):
        unittest.TestCase.__init__(self, *args, **kwargs)
        log.FluLogKeeper.__init__(self)
        log.Logger.__init__(self, self)
