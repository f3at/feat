# -*- coding: utf-8 -*-
# -*- Mode: Python -*-
# vi:si:et:sw=4:sts=4:ts=4

import itertools
import types

from twisted.spread import jelly

from feat.common.serialization import banana
from feat.interface.serialization import *

from . import common_serialization


class BananaConvertersTest(common_serialization.ConverterTest):

    def setUp(self):
        common_serialization.ConverterTest.setUp(self)
        ext = self.externalizer
        self.serializer = banana.Serializer(externalizer = ext)
        self.unserializer = banana.Unserializer(externalizer = ext)
