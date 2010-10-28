from feat.common import log
from feat.interface import logging
import sys

try:
    a = already_done
except NameError:
    sys.stderr = file('test.log', 'a')
    log.FluLogKeeper.init()
    already_done = True


