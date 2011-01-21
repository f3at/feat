from feat.test import common
from feat.agents.base import partners, recipient


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
        self.agent = common.DummyRecordNode(self)
        self.partners = Partners(self.agent)

    def testQueryingHandlers(self):
        self.assertEqual(FirstPartner,
                         self.partners.query_handler("first_agent"))
        self.assertEqual(SpecialPartner,
                         self.partners.query_handler("first_agent", "special"))
        self.assertEqual(SecondPartner,
                         self.partners.query_handler("second_agent"))
        self.assertEqual(DefaultPartner,
                         self.partners.query_handler("second_agent", "role"))

        self.assertEqual(partners.BasePartner,
                         OtherPartners.query_handler("second_agent", "role"))
        self.assertEqual(SecondPartner,
                         OtherPartners.query_handler("first_agent"))
        self.assertEqual(FirstPartner,
                         OtherPartners.query_handler("second_agent"))

    def testQueringPartners(self):
        partners = [
            self._generate_partner(FirstPartner),
            self._generate_partner(SecondPartner),
            self._generate_partner(SecondPartner),
            self._generate_partner(SecondPartner),
            self._generate_partner(SpecialPartner)]

        self._inject_partners(partners)

        self.assertIsInstance(self.partners.query('first'), FirstPartner)
        self.assertIsInstance(self.partners.first, FirstPartner)

        seconds = self.partners.query('second')
        self.assertEqual(seconds, self.partners.second)
        self.assertIsInstance(seconds, list)
        self.assertEqual(3, len(seconds))
        [self.assertIsInstance(x, SecondPartner) for x in seconds]

        specials = self.partners.query('special')
        self.assertEqual(specials, self.partners.special)
        self.assertIsInstance(specials, list)
        self.assertEqual(1, len(specials))
        self.assertIsInstance(specials[0], SpecialPartner)

    def _inject_partners(self, partners):

        def get_descriptor():
            return DummyDesc(partners)

        setattr(self.agent, 'get_descriptor', get_descriptor)

    def _generate_partner(self, factory):
        recp = recipient.dummy_agent()
        return factory(recp)
