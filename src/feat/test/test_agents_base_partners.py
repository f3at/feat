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
from feat.test import common
from feat.agents.base import partners
from feat.agencies import recipient


class FirstPartner(partners.BasePartner):
    pass


class SpecialPartner(partners.BasePartner):
    pass


class SecondPartner(partners.BasePartner):
    pass


class DefaultPartner(partners.BasePartner):
    pass


class Partners(partners.Partners):

    default_handler = DefaultPartner
    partners.has_one("first", "first_agent", FirstPartner)
    partners.has_many("special", "first_agent", SpecialPartner, "special")
    partners.has_many("second", "second_agent", SecondPartner)


class OtherPartners(partners.Partners):

    partners.has_one("first", "first_agent", SecondPartner)
    partners.has_many("second", "second_agent", FirstPartner)


class DummyDesc(object):

    def __init__(self, partners):
        self.partners = partners


class TestPartners(common.TestCase):

    def setUp(self):
        self.agent = common.DummyRecorderNode(self)
        self.partners = Partners(self.agent)

    def testQueryingHandlers(self):
        self.assertEqual(FirstPartner,
                         self.partners.query_handler("first_agent"))
        self.assertEqual(FirstPartner,
                         self.partners.query_handler("first_agent"),
                         "undefined role")
        self.assertEqual(SpecialPartner,
                         self.partners.query_handler("first_agent", "special"))
        self.assertEqual(SecondPartner,
                         self.partners.query_handler("second_agent"))

        self.assertEqual(FirstPartner,
                         OtherPartners.query_handler("second_agent", "role"))
        self.assertEqual(SecondPartner,
                         OtherPartners.query_handler("first_agent"))
        self.assertEqual(FirstPartner,
                         OtherPartners.query_handler("second_agent"))

    def testQueringPartners(self):
        self._generate_partners()

        self.assertIsInstance(self.partners.query('first'), FirstPartner)
        self.assertIsInstance(self.partners.first, FirstPartner)

        seconds = self.partners.query('second')
        self.assertEqual(seconds, self.partners.query(SecondPartner))
        self.assertEqual(seconds, self.partners.second)
        self.assertIsInstance(seconds, list)
        self.assertEqual(3, len(seconds))
        [self.assertIsInstance(x, SecondPartner) for x in seconds]

        specials = self.partners.query('special')
        self.assertEqual(specials, self.partners.query(SpecialPartner))
        self.assertEqual(specials, self.partners.special)
        self.assertIsInstance(specials, list)
        self.assertEqual(1, len(specials))
        self.assertIsInstance(specials[0], SpecialPartner)

    def testQueringWithRole(self):
        self._generate_partners()
        specials = self.partners.all_with_role("special")
        self.assertIsInstance(specials, list)
        self.assertEqual(3, len(specials))

    def _generate_partners(self):
        partners = [
            self._generate_partner(FirstPartner),
            self._generate_partner(SecondPartner, 'special'),
            self._generate_partner(SecondPartner, 'special'),
            self._generate_partner(SecondPartner, 'special'),
            self._generate_partner(SpecialPartner)]

        self._inject_partners(partners)

    def _inject_partners(self, partners):

        def get_descriptor():
            return DummyDesc(partners)

        setattr(self.agent, 'get_descriptor', get_descriptor)

    def _generate_partner(self, factory, role=None):
        recp = recipient.dummy_agent()
        return factory(recp, role=role)
