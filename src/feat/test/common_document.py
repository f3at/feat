# -*- coding: utf-8 -*-
# -*- Mode: Python -*-
# vi:si:et:sw=4:sts=4:ts=4

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

import re

from zope.interface import Interface, implements

from feat.common import defer
from feat.web import document


### Interfaces ###


class IAnimal(Interface):

    def get_name(self):
        pass


class IWinged(IAnimal):

    def can_fly(self):
        pass


class IMammal(IAnimal):

    def is_viviparous(self):
        pass


class IBird(IAnimal, IWinged):

    def is_migratory(self):
        pass


class IHuman(IMammal):

    def get_mortgage(self):
        pass


class IBat(IMammal, IWinged):

    def use_echolocation(self):
        pass


### Classes ###


class Animal(object):

    implements(IAnimal)

    def __init__(self, name):
        self._name = name

    ### IAnimal Methods ###

    def get_name(self):
        return self._name


class Mammal(Animal):

    implements(IMammal)

    def __init__(self, name, viviparous):
        Animal.__init__(self, name)
        self._viviparaous = viviparous

    ### IMammal Methods ###

    def is_viviparous(self):
        return self._viviparaous


class Bird(Animal):

    implements(IBird, IWinged)

    def __init__(self, name, fly, migratory):
        Animal.__init__(self, name)
        self._fly = fly
        self._migratory = migratory

    def __eq__(self, other):
        return (IBird.providedBy(other)
                and (other.get_name() == self._name)
                and (other.can_fly() == self._fly)
                and (other.is_migratory() == self._migratory))

    ### IBird Methods ###

    def is_migratory(self):
        return self._migratory

    ### IWinged Methods ###

    def can_fly(self):
        return self._fly


class Human(Mammal):

    implements(IHuman)

    def __init__(self, name, mortgage):
        Mammal.__init__(self, name, True)
        self._mortgage = mortgage

    def __eq__(self, other):
        return (IHuman.providedBy(other)
                and (other.get_name() == self._name)
                and (other.get_mortgage() == self._mortgage))

    ### IHuman Methods ###

    def get_mortgage(self):
        return self._mortgage


class Bat(Mammal):

    implements(IBat, IWinged)

    def __init__(self, name, echolocation):
        Mammal.__init__(self, name, True)
        self._echolocation = echolocation

    def __eq__(self, other):
        return (IBat.providedBy(other)
                and (other.get_name() == self._name)
                and (other.use_echolocation() == self._echolocation))

    ### IWinged Methods ###

    def can_fly(self):
        return True

    ### IBat Methods ###

    def use_echolocation(self):
        return self._echolocation


### Config Readers/Writers ###


class Reader(object):

    implements(document.IReader)

    def __init__(self, reader_fun):
        self.reader_fun = reader_fun

    def read(self, doc):
        return self.reader_fun(doc)


class Writer(object):

    implements(document.IWriter)

    def __init__(self, writer_fun):
        self.writer_fun = writer_fun

    def write(self, doc, obj):
        return self.writer_fun(doc, obj)


CONFIG_MIME = "config"


def read_config_line(doc, name):
    line = doc.readline().strip('\n')
    pair = line.split(':', 1)
    if (len(pair) < 2) or (pair[0] != name):
        raise TypeError()
    return pair[1]


def write_config_line(doc, name, value):
    doc.write("%s:%s\n" % (name, value))


def human2config(doc, human):
    doc.write("[HUMMAN]\n")
    write_config_line(doc, "name", human.get_name())
    write_config_line(doc, "mortgage", human.get_mortgage())


def config2human(doc):
    l = doc.readline()
    if l != "[HUMMAN]\n":
        raise TypeError()
    return create_config_human(doc)


def create_config_human(doc):
    name = read_config_line(doc, "name")
    mortgage = int(read_config_line(doc, "mortgage"))
    return Human(name, mortgage)


def bat2config(doc, bat):
    doc.write("[BAT]\n")
    write_config_line(doc, "name", bat.get_name())
    write_config_line(doc, "echolocation", bat.use_echolocation())
    return defer.succeed(doc)


def config2bat(doc):
    l = doc.readline()
    if l != "[BAT]\n":
        raise TypeError()
    return defer.succeed(create_config_bat(doc))


def create_config_bat(doc):
    name = read_config_line(doc, "name")
    echolocation = read_config_line(doc, "echolocation").upper() == "TRUE"
    return Bat(name, echolocation)


def bird2config(doc, bird):
    doc.write("[BIRD]\n")
    write_config_line(doc, "name", bird.get_name())
    write_config_line(doc, "fly", bird.can_fly())
    write_config_line(doc, "migratory", bird.is_migratory())


def config2bird(doc):
    l = doc.readline()
    if l != "[BIRD]\n":
        raise TypeError()
    return create_config_bird(doc)


def create_config_bird(doc):
    name = read_config_line(doc, "name")
    fly = read_config_line(doc, "fly").upper() == "TRUE"
    migratory = read_config_line(doc, "migratory").upper() == "TRUE"
    return Bird(name, fly, migratory)


def config2mammal(doc):
    l = doc.readline()
    if l == "[HUMMAN]\n":
        return defer.succeed(create_config_human(doc))
    if l == "[BAT]\n":
        return defer.succeed(create_config_bat(doc))
    raise TypeError()


def config2winged(doc):
    l = doc.readline()
    if l == "[BIRD]\n":
        return defer.succeed(create_config_bird(doc))
    if l == "[BAT]\n":
        return defer.succeed(create_config_bat(doc))
    raise TypeError()


def config2animal(doc):
    l = doc.readline()
    if l == "[BIRD]\n":
        return defer.succeed(create_config_bird(doc))
    if l == "[BAT]\n":
        return defer.succeed(create_config_bat(doc))
    if l == "[HUMMAN]\n":
        return defer.succeed(create_config_human(doc))
    raise TypeError()


human_config_writer = Writer(human2config)
human_config_reader = Reader(config2human)
bat_config_writer = Writer(bat2config)
bat_config_reader = Reader(config2bat)
bird_config_writer = Writer(bird2config)
bird_config_reader = Reader(config2bird)
mammal_config_reader = Reader(config2mammal)
winged_config_reader = Reader(config2winged)
animal_config_reader = Reader(config2animal)


## XML Readers/Writers ##


XML_MIME = "xml"


def write_xml(doc, type, **kwargs):
    doc.write("<?xml version=\"1.0\" encoding=\"%s\"?>\n" % doc.encoding)
    doc.write("<%s size=%d>\n" % (type, len(kwargs)))
    for name, value in kwargs.items():
        doc.write("  <%s>%s</%s>\n" % (name, value, name))
    doc.write("</%s>\n" % type)


def read_xml(doc):
    header = doc.readline()
    m = re.match('\s*<\?xml\s*version="1.0"\s*encoding='
                 '"(?P<encoding>[^\"]*)"\s*\?>\s*\n', header)
    if not m:
        raise TypeError()
    expected_encoding = doc.encoding
    if expected_encoding and (expected_encoding != m.group("encoding")):
        raise TypeError()
    m = re.match("\s*<\s*(?P<type>[^\s]*)\s*size="
                 "(?P<size>\d*)\s*>\s*\n", doc.readline())
    if not m:
        raise TypeError()
    type = m.group("type")
    values = {}
    size = int(m.group("size"))
    for _ in range(size):
        m = re.match("\s*<\s*(?P<id>[^\s]*)\s*>(?P<value>.*)"
                     "</\s*(?P=id)\s*>\s*\n", doc.readline())
        if not m:
            raise TypeError()
        values[str(m.group("id"))] = m.group("value")
    m = re.match("\s*</\s*(?P<type>[^\s]*)\s*>\s*\n", doc.readline())
    if (not m) or (m.group("type") != type):
        raise TypeError()
    return type, values


def human2xml(doc, human):
    write_xml(doc, "HUMMAN",
             name=human.get_name(),
             mortgage=human.get_mortgage())


def xml2human(doc):
    type, values = read_xml(doc)
    if type != "HUMMAN":
        raise TypeError()
    return defer.succeed(create_xml_human(**values))


def create_xml_human(name, mortgage):
    return Human(name, int(mortgage))


def bat2xml(doc, bat):
    write_xml(doc, "BAT",
             name=bat.get_name(),
             echolocation=bat.use_echolocation())
    return defer.succeed(doc)


def xml2bat(doc):
    type, values = read_xml(doc)
    if type != "BAT":
        raise TypeError()
    return create_xml_bat(**values)


def create_xml_bat(name, echolocation):
    return Bat(name, echolocation.upper() == "TRUE")


def bird2xml(doc, bird):
    write_xml(doc, "BIRD",
             name=bird.get_name(),
             fly=bird.can_fly(),
             migratory=bird.is_migratory())
    return defer.succeed(doc)


def xml2bird(doc):
    type, values = read_xml(doc)
    if type != "BIRD":
        raise TypeError()
    return defer.succeed(create_xml_bird(**values))


def create_xml_bird(name, fly, migratory):
    return Bird(name, fly.upper() == "TRUE", migratory.upper() == "TRUE")


def xml2mammal(doc):
    type, values = read_xml(doc)
    if type == "HUMMAN":
        return defer.succeed(create_xml_human(**values))
    if type == "BAT":
        return defer.succeed(create_xml_bat(**values))
    raise TypeError()


def xml2winged(doc):
    type, values = read_xml(doc)
    if type == "BIRD":
        return defer.succeed(create_xml_bird(**values))
    if type == "BAT":
        return defer.succeed(create_xml_bat(**values))
    raise TypeError()


def xml2animal(doc):
    type, values = read_xml(doc)
    if type == "BIRD":
        return defer.succeed(create_xml_bird(**values))
    if type == "BAT":
        return defer.succeed(create_xml_bat(**values))
    if type == "HUMMAN":
        return defer.succeed(create_xml_human(**values))
    raise TypeError()


human_xml_writer = Writer(human2xml)
human_xml_reader = Reader(xml2human)
bat_xml_writer = Writer(bat2xml)
bat_xml_reader = Reader(xml2bat)
bird_xml_writer = Writer(bird2xml)
bird_xml_reader = Reader(xml2bird)
mammal_xml_reader = Reader(xml2mammal)
winged_xml_reader = Reader(xml2winged)
animal_xml_reader = Reader(xml2animal)


### Controlled Samples ###


def get_samples():

    def init_result(*entries):
        result = {}
        for name in entries:
            result[name] = {}
            result[name]["interface"] = None
            result[name]["instance"] = None
            result[name]["config"] = {}
            result[name]["xml"] = {}
        return result

    result = init_result("human", "bat", "bird")

    d = result["human"]
    d["interface"] = IHuman
    d["instance"] = Human(u"Борис", 666000)
    d["config"]["utf8"] = "[HUMMAN]\n" \
                          "name:\xd0\x91\xd0\xbe\xd1\x80\xd0\xb8\xd1\x81\n" \
                          "mortgage:666000\n"
    d["config"]["iso5"] = "[HUMMAN]\n" \
                          "name:\xb1\xde\xe0\xd8\xe1\n" \
                          "mortgage:666000\n"
    d["xml"]["utf8"] = '<?xml version="1.0" encoding="utf8"?>\n' \
                       '<HUMMAN size=2>\n' \
                       '  <name>\xd0\x91\xd0\xbe\xd1\x80' \
                               '\xd0\xb8\xd1\x81</name>\n' \
                       '  <mortgage>666000</mortgage>\n' \
                       '</HUMMAN>\n'
    d["xml"]["iso5"] = '<?xml version="1.0" encoding="iso-8859-5"?>\n' \
                       '<HUMMAN size=2>\n' \
                       '  <name>\xb1\xde\xe0\xd8\xe1</name>\n' \
                       '  <mortgage>666000</mortgage>\n' \
                       '</HUMMAN>\n'

    d = result["bat"]
    d["interface"] = IBat
    d["instance"] = Bat(u"Bruce Waîyñ", False)
    d["config"]["utf8"] = "[BAT]\n" \
                          "name:Bruce Wa\xc3\xaey\xc3\xb1\n" \
                          "echolocation:False\n"
    d["config"]["iso1"] = "[BAT]\n" \
                          "name:Bruce Wa\xeey\xf1\n" \
                          "echolocation:False\n"
    d["xml"]["utf8"] = '<?xml version="1.0" encoding="utf8"?>\n' \
                       '<BAT size=2>\n' \
                       '  <echolocation>False</echolocation>\n' \
                       '  <name>Bruce Wa\xc3\xaey\xc3\xb1</name>\n' \
                       '</BAT>\n'
    d["xml"]["iso1"] = '<?xml version="1.0" encoding="iso-8859-1"?>\n' \
                       '<BAT size=2>\n' \
                       '  <echolocation>False</echolocation>\n' \
                       '  <name>Bruce Wa\xeey\xf1</name>\n' \
                       '</BAT>\n'

    d = result["bird"]
    d["interface"] = IBird
    d["instance"] = Bird(u"オオハシ科", True, False)
    d["config"]["utf8"] = "[BIRD]\n" \
                          "name:\xe3\x82\xaa\xe3\x82\xaa\xe3\x83\x8f" \
                               "\xe3\x82\xb7\xe7\xa7\x91\n" \
                          "fly:True\n" \
                          "migratory:False\n"
    d["config"]["big5"] = "[BIRD]\n" \
                          "name:\xc7B\xc7B\xc7g\xc7O\xac\xec\n" \
                          "fly:True\n" \
                          "migratory:False\n"
    d["xml"]["utf8"] = '<?xml version="1.0" encoding="utf8"?>\n' \
                       '<BIRD size=3>\n' \
                       '  <fly>True</fly>\n' \
                       '  <name>\xe3\x82\xaa\xe3\x82\xaa\xe3\x83\x8f\xe3' \
                               '\x82\xb7\xe7\xa7\x91</name>\n' \
                       '  <migratory>False</migratory>\n' \
                       '</BIRD>\n'
    d["xml"]["big5"] = '<?xml version="1.0" encoding="big5"?>\n' \
                       '<BIRD size=3>\n' \
                       '  <fly>True</fly>\n' \
                       '  <name>\xc7B\xc7B\xc7g\xc7O\xac\xec</name>\n' \
                       '  <migratory>False</migratory>\n' \
                       '</BIRD>\n'

    return result
