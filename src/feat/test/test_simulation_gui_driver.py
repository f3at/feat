from twisted.internet import defer

from feat.common.text_helper import format_block
from feat.test import common
from feat.agents.base import descriptor, agent
from feat.agencies import agency


try:
    from feat.simulation.simgui.core import driver
    SKIP_TEST = False
except ImportError, e:
    SKIP_TEST = str(e)

dot_template = """digraph G {\nsubgraph cluster_1 \
{\ncolor=lightblue;\nstyle=filled;\nlabel=lobby;\nsubgraph cluster_0 \
{\ncolor=lightyellow;\nstyle=filled;\nlabel="agency 1";\n"%(id)s" \
[URL="%(id)s", color=white, style=filled, \
label=DummyAgent];\n}\n\n}\n\n}\n"""


class TestGuiDriver(common.TestCase):

    if SKIP_TEST:
        skip = SKIP_TEST

    def setUp(self):
        self.driver = driver.GuiDriver()

    @defer.inlineCallbacks
    def testAgency(self):
        test = 'agency = spawn_agency()\n'
        d = self.cb_after(None, self.driver._parser, 'on_finish')
        self.driver.process(test)
        yield d
        self.assertEqual(1, len(self.driver._agencies))
        self.assertEqual(self.driver.export_to_dot(), 'digraph G {\n}\n')

    @defer.inlineCallbacks
    def testAgent(self):
        test = "agency = spawn_agency()\n \
                agency.start_agent(descriptor_factory('descriptor'))\n"
        d = self.cb_after(None, self.driver._parser, 'on_finish')
        self.driver.process(test)
        yield d
        ag = self.driver._agencies[0]
        self.assertEqual(1, len(ag._agents))
        id = ag._agents[0]._descriptor.doc_id
        self.assertEqual(self.driver.export_to_dot(),
                         dot_template % {'id': id})
        ag2 = self.driver.find_agency(id)
        self.assertTrue(isinstance(ag2, agency.Agency))
        self.assertEqual(ag, ag2)
        a = self.driver.find_agent(id)
        self.assertTrue(isinstance(a, agency.AgencyAgent))
        self.assertTrue(isinstance(a.get_agent(), agent.BaseAgent))
        self.assertEqual(a, ag._agents[0])
        self.assertEqual(a.snapshot(), id)
        desc = a.get_descriptor()
        self.assertTrue(isinstance(desc, descriptor.Descriptor))

    def testError(self):
        test = 'agency.start_agent()\n'
        self.driver.process(test)
        self.assertEqual(self.driver.get_error(), 'Unknown variable agency')

    @defer.inlineCallbacks
    def testClearDriver(self):
        test = "agency = spawn_agency()\n \
                agency.start_agent(descriptor_factory('descriptor'))\n"
        d = self.cb_after(None, self.driver._parser, 'on_finish')
        self.driver.process(test)
        yield d
        yield self.driver.clear()
        self.assertEqual(0, len(self.driver._agencies))
