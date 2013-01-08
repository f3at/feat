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
# -*- coding: UTF-8 -*-
# vi:si:et:sw=4:sts=4:ts=4

from feat.test import common, common_document

from feat.common import defer
from feat.web import document


from feat.test.common_document import *


class TestDocuments(common.TestCase):

    def register_config(self):
        registry = self.registry
        # Half registered with writer/reader
        registry.register_writer(human_config_writer, CONFIG_MIME, IHuman)
        registry.register_reader(human_config_reader, CONFIG_MIME, IHuman)
        registry.register_writer(bat_config_writer, CONFIG_MIME, IBat)
        registry.register_reader(bat_config_reader, CONFIG_MIME, IBat)
        # Half registered with function
        registry.register_writer(bird2config, CONFIG_MIME, IBird)
        registry.register_reader(config2bird, CONFIG_MIME, IBird)
        registry.register_reader(config2mammal, CONFIG_MIME, IMammal)
        registry.register_reader(config2winged, CONFIG_MIME, IWinged)
        registry.register_reader(config2animal, CONFIG_MIME, IAnimal)

    def register_xml(self):
        registry = self.registry
        # Half registered with writer/reader
        registry.register_writer(human_xml_writer, XML_MIME, IHuman)
        registry.register_reader(human_xml_reader, XML_MIME, IHuman)
        registry.register_writer(bat_xml_writer, XML_MIME, IBat)
        registry.register_reader(bat_xml_reader, XML_MIME, IBat)
        # Half registered with function
        registry.register_writer(bird2xml, XML_MIME, IBird)
        registry.register_reader(xml2bird, XML_MIME, IBird)
        registry.register_reader(xml2mammal, XML_MIME, IMammal)
        registry.register_reader(xml2winged, XML_MIME, IWinged)
        registry.register_reader(xml2animal, XML_MIME, IAnimal)

    def register_all(self):
        self.register_config()
        self.register_xml()

    def setUp(self):
        self.registry = document.Registry()

    @defer.inlineCallbacks
    def testSubregistry(self):
        registry = self.registry.create_subregistry()
        self.assertIsInstance(registry, document.Registry)

        registry.register_writer(human_xml_writer, XML_MIME, IHuman)
        samples = get_samples()
        doc = document.WritableDocument(XML_MIME, 'utf8')
        human = samples["human"]["instance"]

        written = yield registry.write(doc, human)
        doc = document.WritableDocument(XML_MIME, 'utf8')
        d = self.registry.write(doc, human)
        self.assertFailure(d, document.NoWriterFoundError)
        yield d

    def testSimpleWriteRead(self):

        def write(obj, iface, type, encoding="utf8"):
            doc = document.WritableDocument(type, encoding)
            return self.registry.write(doc, obj).addCallback(read, obj, iface)

        def read(in_doc, obj, iface):
            data = in_doc.get_data()
            out_doc = document.ReadableDocument(data, in_doc.mime_type,
                                                in_doc.encoding)
            return self.registry.read(out_doc, iface).addCallback(compare, obj)

        def compare(result, obj):
            self.assertEqual(obj, result)

        samples = get_samples()
        human = samples["human"]["instance"]
        bat = samples["bat"]["instance"]
        bird = samples["bird"]["instance"]

        self.register_all()

        d = defer.succeed(None)

        # With UTF8 encoding

        d.addCallback(defer.drop_param, write, human, IHuman, CONFIG_MIME)
        d.addCallback(defer.drop_param, write, human, IHuman, XML_MIME)
        d.addCallback(defer.drop_param, write, bat, IBat, CONFIG_MIME)
        d.addCallback(defer.drop_param, write, bat, IBat, XML_MIME)
        d.addCallback(defer.drop_param, write, bird, IBird, CONFIG_MIME)
        d.addCallback(defer.drop_param, write, bird, IBird, XML_MIME)
        d.addCallback(defer.drop_param, write, human, IMammal, CONFIG_MIME)
        d.addCallback(defer.drop_param, write, human, IMammal, XML_MIME)
        d.addCallback(defer.drop_param, write, bat, IMammal, CONFIG_MIME)
        d.addCallback(defer.drop_param, write, bat, IMammal, XML_MIME)
        d.addCallback(defer.drop_param, write, bird, IWinged, CONFIG_MIME)
        d.addCallback(defer.drop_param, write, bird, IWinged, XML_MIME)
        d.addCallback(defer.drop_param, write, bat, IWinged, CONFIG_MIME)
        d.addCallback(defer.drop_param, write, bat, IWinged, XML_MIME)
        d.addCallback(defer.drop_param, write, bird, IAnimal, CONFIG_MIME)
        d.addCallback(defer.drop_param, write, bird, IAnimal, XML_MIME)
        d.addCallback(defer.drop_param, write, human, IAnimal, XML_MIME)
        d.addCallback(defer.drop_param, write, human, IAnimal, CONFIG_MIME)

        # With other encodings

        d.addCallback(defer.drop_param, write, human, IHuman,
                      CONFIG_MIME, "iso-8859-5")
        d.addCallback(defer.drop_param, write, human, IHuman,
                      XML_MIME, "iso-8859-5")
        d.addCallback(defer.drop_param, write, human, IMammal,
                      CONFIG_MIME, "iso-8859-5")
        d.addCallback(defer.drop_param, write, human, IMammal,
                      XML_MIME, "iso-8859-5")
        d.addCallback(defer.drop_param, write, human, IAnimal,
                      XML_MIME, "iso-8859-5")
        d.addCallback(defer.drop_param, write, human, IAnimal,
                      CONFIG_MIME, "iso-8859-5")

        d.addCallback(defer.drop_param, write, bat, IBat,
                      CONFIG_MIME, "iso-8859-1")
        d.addCallback(defer.drop_param, write, bat, IBat,
                      XML_MIME, "iso-8859-1")
        d.addCallback(defer.drop_param, write, bat, IMammal,
                      CONFIG_MIME, "iso-8859-1")
        d.addCallback(defer.drop_param, write, bat, IMammal,
                      XML_MIME, "iso-8859-1")
        d.addCallback(defer.drop_param, write, bat, IWinged,
                      CONFIG_MIME, "iso-8859-1")
        d.addCallback(defer.drop_param, write, bat, IWinged,
                      XML_MIME, "iso-8859-1")

        d.addCallback(defer.drop_param, write, bird, IBird,
                      CONFIG_MIME, "big5")
        d.addCallback(defer.drop_param, write, bird, IBird,
                      XML_MIME, "big5")
        d.addCallback(defer.drop_param, write, bird, IWinged,
                      CONFIG_MIME, "big5")
        d.addCallback(defer.drop_param, write, bird, IWinged,
                      XML_MIME, "big5")
        d.addCallback(defer.drop_param, write, bird, IAnimal,
                      CONFIG_MIME, "big5")
        d.addCallback(defer.drop_param, write, bird, IAnimal,
                      XML_MIME, "big5")

        return d

    def testSimpleReadWrite(self):

        def read(data, iface, type, encoding="utf8"):
            reader = document.ReadableDocument(data, type, encoding)
            d = self.registry.read(reader, iface)
            return d.addCallback(write, reader, data)

        def write(obj, reader, data):
            writer = document.WritableDocument(reader.mime_type,
                                               reader.encoding)
            return self.registry.write(writer, obj).addCallback(compare, data)

        def compare(writer, data):
            result = writer.get_data()
            self.assertEqual(data, result)

        samples = get_samples()
        human_config_utf8 = samples["human"]["config"]["utf8"]
        human_xml_utf8 = samples["human"]["xml"]["utf8"]
        human_config_iso5 = samples["human"]["config"]["iso5"]
        human_xml_iso5 = samples["human"]["xml"]["iso5"]
        bat_config_utf8 = samples["bat"]["config"]["utf8"]
        bat_xml_utf8 = samples["bat"]["xml"]["utf8"]
        bat_config_iso1 = samples["bat"]["config"]["iso1"]
        bat_xml_iso1 = samples["bat"]["xml"]["iso1"]
        bird_config_utf8 = samples["bird"]["config"]["utf8"]
        bird_xml_utf8 = samples["bird"]["xml"]["utf8"]
        bird_config_big5 = samples["bird"]["config"]["big5"]
        bird_xml_big5 = samples["bird"]["xml"]["big5"]

        self.register_all()

        d = defer.succeed(None)

        # With UTF8 encoding

        d.addCallback(defer.drop_param, read,
                      human_config_utf8, IHuman, CONFIG_MIME)
        d.addCallback(defer.drop_param, read,
                      human_xml_utf8, IHuman, XML_MIME)
        d.addCallback(defer.drop_param, read,
                      bat_config_utf8, IBat, CONFIG_MIME)
        d.addCallback(defer.drop_param, read,
                      bat_xml_utf8, IBat, XML_MIME)
        d.addCallback(defer.drop_param, read,
                      bird_config_utf8, IBird, CONFIG_MIME)
        d.addCallback(defer.drop_param, read,
                      bird_xml_utf8, IBird, XML_MIME)
        d.addCallback(defer.drop_param, read,
                      human_config_utf8, IMammal, CONFIG_MIME)
        d.addCallback(defer.drop_param, read,
                      human_xml_utf8, IMammal, XML_MIME)
        d.addCallback(defer.drop_param, read,
                      bat_config_utf8, IMammal, CONFIG_MIME)
        d.addCallback(defer.drop_param, read,
                      bat_xml_utf8, IMammal, XML_MIME)
        d.addCallback(defer.drop_param, read,
                      bird_config_utf8, IWinged, CONFIG_MIME)
        d.addCallback(defer.drop_param, read,
                      bird_xml_utf8, IWinged, XML_MIME)
        d.addCallback(defer.drop_param, read,
                      bat_config_utf8, IWinged, CONFIG_MIME)
        d.addCallback(defer.drop_param, read,
                      bat_xml_utf8, IWinged, XML_MIME)
        d.addCallback(defer.drop_param, read,
                      human_config_utf8, IAnimal, CONFIG_MIME)
        d.addCallback(defer.drop_param, read,
                      human_xml_utf8, IAnimal, XML_MIME)
        d.addCallback(defer.drop_param, read,
                      bat_config_utf8, IAnimal, CONFIG_MIME)
        d.addCallback(defer.drop_param, read,
                      bat_xml_utf8, IAnimal, XML_MIME)
        d.addCallback(defer.drop_param, read,
                      bird_config_utf8, IAnimal, CONFIG_MIME)
        d.addCallback(defer.drop_param, read,
                      bird_xml_utf8, IAnimal, XML_MIME)

        # With other encodings

        d.addCallback(defer.drop_param, read,
                      human_config_iso5, IHuman, CONFIG_MIME, "iso-8859-5")
        d.addCallback(defer.drop_param, read,
                      human_xml_iso5, IHuman, XML_MIME, "iso-8859-5")
        d.addCallback(defer.drop_param, read,
                      bat_config_iso1, IBat, CONFIG_MIME, "iso-8859-1")
        d.addCallback(defer.drop_param, read,
                      bat_xml_iso1, IBat, XML_MIME, "iso-8859-1")
        d.addCallback(defer.drop_param, read,
                      bird_config_big5, IBird, CONFIG_MIME, "big5")
        d.addCallback(defer.drop_param, read,
                      bird_xml_big5, IBird, XML_MIME, "big5")
        d.addCallback(defer.drop_param, read,
                      human_config_iso5, IMammal, CONFIG_MIME, "iso-8859-5")
        d.addCallback(defer.drop_param, read,
                      human_xml_iso5, IMammal, XML_MIME, "iso-8859-5")
        d.addCallback(defer.drop_param, read,
                      bat_config_iso1, IMammal, CONFIG_MIME, "iso-8859-1")
        d.addCallback(defer.drop_param, read,
                      bat_xml_iso1, IMammal, XML_MIME, "iso-8859-1")
        d.addCallback(defer.drop_param, read,
                      bird_config_big5, IWinged, CONFIG_MIME, "big5")
        d.addCallback(defer.drop_param, read,
                      bird_xml_big5, IWinged, XML_MIME, "big5")
        d.addCallback(defer.drop_param, read,
                      bat_config_iso1, IWinged, CONFIG_MIME, "iso-8859-1")
        d.addCallback(defer.drop_param, read,
                      bat_xml_iso1, IWinged, XML_MIME, "iso-8859-1")
        d.addCallback(defer.drop_param, read,
                      human_config_iso5, IAnimal, CONFIG_MIME, "iso-8859-5")
        d.addCallback(defer.drop_param, read,
                      human_xml_iso5, IAnimal, XML_MIME, "iso-8859-5")
        d.addCallback(defer.drop_param, read,
                      bat_config_iso1, IAnimal, CONFIG_MIME, "iso-8859-1")
        d.addCallback(defer.drop_param, read,
                      bat_xml_iso1, IAnimal, XML_MIME, "iso-8859-1")
        d.addCallback(defer.drop_param, read,
                      bird_config_big5, IAnimal, CONFIG_MIME, "big5")
        d.addCallback(defer.drop_param, read,
                      bird_xml_big5, IAnimal, XML_MIME, "big5")

        return d

    def testAsString(self):

        def check(obj, type, expected, encoding="utf8"):
            d = self.registry.as_string(obj, type, encoding)
            return d.addCallback(compare, expected)

        def compare(result, expected):
            self.assertEqual(expected, result)

        samples = get_samples()
        human = samples["human"]["instance"]
        bat = samples["bat"]["instance"]
        bird = samples["bird"]["instance"]
        human_config_utf8 = samples["human"]["config"]["utf8"]
        human_xml_utf8 = samples["human"]["xml"]["utf8"]
        human_config_iso5 = samples["human"]["config"]["iso5"]
        human_xml_iso5 = samples["human"]["xml"]["iso5"]
        bat_config_utf8 = samples["bat"]["config"]["utf8"]
        bat_xml_utf8 = samples["bat"]["xml"]["utf8"]
        bat_config_iso1 = samples["bat"]["config"]["iso1"]
        bat_xml_iso1 = samples["bat"]["xml"]["iso1"]
        bird_config_utf8 = samples["bird"]["config"]["utf8"]
        bird_xml_utf8 = samples["bird"]["xml"]["utf8"]
        bird_config_big5 = samples["bird"]["config"]["big5"]
        bird_xml_big5 = samples["bird"]["xml"]["big5"]

        self.register_all()

        d = defer.succeed(None)

        # With UTF8 encoding

        d.addCallback(defer.drop_param, check,
                      human, CONFIG_MIME, human_config_utf8)
        d.addCallback(defer.drop_param, check,
                      human, XML_MIME, human_xml_utf8)
        d.addCallback(defer.drop_param, check,
                      bat, CONFIG_MIME, bat_config_utf8)
        d.addCallback(defer.drop_param, check,
                      bat, XML_MIME, bat_xml_utf8)
        d.addCallback(defer.drop_param, check,
                      bird, CONFIG_MIME, bird_config_utf8)
        d.addCallback(defer.drop_param, check,
                      bird, XML_MIME, bird_xml_utf8)

        # With other encodings

        d.addCallback(defer.drop_param, check,
                      human, CONFIG_MIME, human_config_iso5, "iso-8859-5")
        d.addCallback(defer.drop_param, check,
                      human, XML_MIME, human_xml_iso5, "iso-8859-5")
        d.addCallback(defer.drop_param, check,
                      bat, CONFIG_MIME, bat_config_iso1, "iso-8859-1")
        d.addCallback(defer.drop_param, check,
                      bat, XML_MIME, bat_xml_iso1, "iso-8859-1")
        d.addCallback(defer.drop_param, check,
                      bird, CONFIG_MIME, bird_config_big5, "big5")
        d.addCallback(defer.drop_param, check,
                      bird, XML_MIME, bird_xml_big5, "big5")

        return d

    def testFromString(self):

        def check(data, iface, type, expected, encoding="utf8"):
            d = self.registry.from_string(data, iface, type, encoding)
            return d.addCallback(compare, expected)

        def compare(result, expected):
            self.assertEqual(expected, result)

        samples = get_samples()
        human = samples["human"]["instance"]
        bat = samples["bat"]["instance"]
        bird = samples["bird"]["instance"]
        human_config_utf8 = samples["human"]["config"]["utf8"]
        human_xml_utf8 = samples["human"]["xml"]["utf8"]
        human_config_iso5 = samples["human"]["config"]["iso5"]
        human_xml_iso5 = samples["human"]["xml"]["iso5"]
        bat_config_utf8 = samples["bat"]["config"]["utf8"]
        bat_xml_utf8 = samples["bat"]["xml"]["utf8"]
        bat_config_iso1 = samples["bat"]["config"]["iso1"]
        bat_xml_iso1 = samples["bat"]["xml"]["iso1"]
        bird_config_utf8 = samples["bird"]["config"]["utf8"]
        bird_xml_utf8 = samples["bird"]["xml"]["utf8"]
        bird_config_big5 = samples["bird"]["config"]["big5"]
        bird_xml_big5 = samples["bird"]["xml"]["big5"]

        self.register_all()

        d = defer.succeed(None)

        # With UTF8 Encoding

        d.addCallback(defer.drop_param, check,
                      human_config_utf8, IHuman, CONFIG_MIME, human)
        d.addCallback(defer.drop_param, check,
                      human_xml_utf8, IHuman, XML_MIME, human)
        d.addCallback(defer.drop_param, check,
                      bat_config_utf8, IBat, CONFIG_MIME, bat)
        d.addCallback(defer.drop_param, check,
                      bat_xml_utf8, IBat, XML_MIME, bat)
        d.addCallback(defer.drop_param, check,
                      bird_config_utf8, IBird, CONFIG_MIME, bird)
        d.addCallback(defer.drop_param, check,
                      bird_xml_utf8, IBird, XML_MIME, bird)
        d.addCallback(defer.drop_param, check,
                      human_config_utf8, IMammal, CONFIG_MIME, human)
        d.addCallback(defer.drop_param, check,
                      human_xml_utf8, IMammal, XML_MIME, human)
        d.addCallback(defer.drop_param, check,
                      bat_config_utf8, IMammal, CONFIG_MIME, bat)
        d.addCallback(defer.drop_param, check,
                      bat_xml_utf8, IMammal, XML_MIME, bat)
        d.addCallback(defer.drop_param, check,
                      bird_config_utf8, IWinged, CONFIG_MIME, bird)
        d.addCallback(defer.drop_param, check,
                      bird_xml_utf8, IWinged, XML_MIME, bird)
        d.addCallback(defer.drop_param, check,
                      bat_config_utf8, IWinged, CONFIG_MIME, bat)
        d.addCallback(defer.drop_param, check,
                      bat_xml_utf8, IWinged, XML_MIME, bat)
        d.addCallback(defer.drop_param, check,
                      human_config_utf8, IAnimal, CONFIG_MIME, human)
        d.addCallback(defer.drop_param, check,
                      human_xml_utf8, IAnimal, XML_MIME, human)
        d.addCallback(defer.drop_param, check,
                      bat_config_utf8, IAnimal, CONFIG_MIME, bat)
        d.addCallback(defer.drop_param, check,
                      bat_xml_utf8, IAnimal, XML_MIME, bat)
        d.addCallback(defer.drop_param, check,
                      bird_config_utf8, IAnimal, CONFIG_MIME, bird)
        d.addCallback(defer.drop_param, check,
                      bird_xml_utf8, IAnimal, XML_MIME, bird)

        # With other Encodings

        d.addCallback(defer.drop_param, check, human_config_iso5,
                      IHuman, CONFIG_MIME, human, "iso-8859-5")
        d.addCallback(defer.drop_param, check, human_xml_iso5,
                      IHuman, XML_MIME, human, "iso-8859-5")
        d.addCallback(defer.drop_param, check, bat_config_iso1,
                      IBat, CONFIG_MIME, bat, "iso-8859-1")
        d.addCallback(defer.drop_param, check, bat_xml_iso1,
                      IBat, XML_MIME, bat, "iso-8859-1")
        d.addCallback(defer.drop_param, check, bird_config_big5,
                      IBird, CONFIG_MIME, bird, "big5")
        d.addCallback(defer.drop_param, check, bird_xml_big5,
                      IBird, XML_MIME, bird, "big5")
        d.addCallback(defer.drop_param, check, human_config_iso5,
                      IMammal, CONFIG_MIME, human, "iso-8859-5")
        d.addCallback(defer.drop_param, check, human_xml_iso5,
                      IMammal, XML_MIME, human, "iso-8859-5")
        d.addCallback(defer.drop_param, check, bat_config_iso1,
                      IMammal, CONFIG_MIME, bat, "iso-8859-1")
        d.addCallback(defer.drop_param, check, bat_xml_iso1,
                      IMammal, XML_MIME, bat, "iso-8859-1")
        d.addCallback(defer.drop_param, check, bird_config_big5,
                      IWinged, CONFIG_MIME, bird, "big5")
        d.addCallback(defer.drop_param, check, bird_xml_big5,
                      IWinged, XML_MIME, bird, "big5")
        d.addCallback(defer.drop_param, check, bat_config_iso1,
                      IWinged, CONFIG_MIME, bat, "iso-8859-1")
        d.addCallback(defer.drop_param, check, bat_xml_iso1,
                      IWinged, XML_MIME, bat, "iso-8859-1")
        d.addCallback(defer.drop_param, check, human_config_iso5,
                      IAnimal, CONFIG_MIME, human, "iso-8859-5")
        d.addCallback(defer.drop_param, check, human_xml_iso5,
                      IAnimal, XML_MIME, human, "iso-8859-5")
        d.addCallback(defer.drop_param, check, bat_config_iso1,
                      IAnimal, CONFIG_MIME, bat, "iso-8859-1")
        d.addCallback(defer.drop_param, check, bat_xml_iso1,
                      IAnimal, XML_MIME, bat, "iso-8859-1")
        d.addCallback(defer.drop_param, check, bird_config_big5,
                      IAnimal, CONFIG_MIME, bird, "big5")
        d.addCallback(defer.drop_param, check, bird_xml_big5,
                      IAnimal, XML_MIME, bird, "big5")

        return d

    def testTranscoding(self):

        def read(iface, type, source_enc, data, target_enc, expected):
            reader = document.ReadableDocument(data, type, source_enc)
            d = self.registry.read(reader, iface)
            return d.addCallback(write, reader, target_enc, expected)

        def write(obj, reader, target_enc, expected):
            writer = document.WritableDocument(reader.mime_type, target_enc)
            d = self.registry.write(writer, obj)
            return d.addCallback(compare, expected)

        def compare(writer, expected):
            result = writer.get_data()
            self.assertEqual(expected, result)

        samples = get_samples()
        human_config_utf8 = samples["human"]["config"]["utf8"]
        human_xml_utf8 = samples["human"]["xml"]["utf8"]
        human_config_iso5 = samples["human"]["config"]["iso5"]
        human_xml_iso5 = samples["human"]["xml"]["iso5"]
        bat_config_utf8 = samples["bat"]["config"]["utf8"]
        bat_xml_utf8 = samples["bat"]["xml"]["utf8"]
        bat_config_iso1 = samples["bat"]["config"]["iso1"]
        bat_xml_iso1 = samples["bat"]["xml"]["iso1"]
        bird_config_utf8 = samples["bird"]["config"]["utf8"]
        bird_xml_utf8 = samples["bird"]["xml"]["utf8"]
        bird_config_big5 = samples["bird"]["config"]["big5"]
        bird_xml_big5 = samples["bird"]["xml"]["big5"]

        self.register_all()

        d = defer.succeed(None)

        d.addCallback(defer.drop_param, read, IHuman, CONFIG_MIME,
                      "utf8", human_config_utf8,
                      "iso-8859-5", human_config_iso5)
        d.addCallback(defer.drop_param, read, IHuman, XML_MIME,
                      "utf8", human_xml_utf8,
                      "iso-8859-5", human_xml_iso5)
        d.addCallback(defer.drop_param, read, IHuman, CONFIG_MIME,
                      "iso-8859-5", human_config_iso5,
                      "utf8", human_config_utf8)
        d.addCallback(defer.drop_param, read, IHuman, XML_MIME,
                      "iso-8859-5", human_xml_iso5,
                      "utf8", human_xml_utf8)

        d.addCallback(defer.drop_param, read, IBat, CONFIG_MIME,
                      "utf8", bat_config_utf8,
                      "iso-8859-1", bat_config_iso1)
        d.addCallback(defer.drop_param, read, IBat, XML_MIME,
                      "utf8", bat_xml_utf8,
                      "iso-8859-1", bat_xml_iso1)
        d.addCallback(defer.drop_param, read, IBat, CONFIG_MIME,
                      "iso-8859-1", bat_config_iso1,
                      "utf8", bat_config_utf8)
        d.addCallback(defer.drop_param, read, IBat, XML_MIME,
                      "iso-8859-1", bat_xml_iso1,
                      "utf8", bat_xml_utf8)

        d.addCallback(defer.drop_param, read, IBird, CONFIG_MIME,
                      "utf8", bird_config_utf8,
                      "big5", bird_config_big5)
        d.addCallback(defer.drop_param, read, IBird, XML_MIME,
                      "utf8", bird_xml_utf8,
                      "big5", bird_xml_big5)
        d.addCallback(defer.drop_param, read, IBird, CONFIG_MIME,
                      "big5", bird_config_big5,
                      "utf8", bird_config_utf8)
        d.addCallback(defer.drop_param, read, IBird, XML_MIME,
                      "big5", bird_xml_big5,
                      "utf8", bird_xml_utf8)

        return d
