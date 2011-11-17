import os
import shutil
import uuid

from zope.interface import implements

from twisted.trial.unittest import SkipTest

from feat.common import defer, adapter
from feat.test import common
from feat.models import texthtml, model, action, value, call, getter, setter
from feat import gateway
from feat.web import document

from feat.models.interface import IModel, IContext, ActionCategory


class TestContext(object):

    implements(IContext)

    def __init__(self, names=(), models=()):
        self.names = names
        self.models = models
        self.remaining = ()

    def make_action_address(self, action):
        return self.make_model_address(self.names + (action.name, ))

    def make_model_address(self, path):
        path = filter(None, path)

    def descend(self, model):
        return TestContext(self.names + (model.name, ),
                           self.models + (model, ))


class HTMLWriterTest(common.TestCase):

    output = True

    @defer.inlineCallbacks
    def setUp(self):
        yield common.TestCase.setUp(self)
        self.document = document.WritableDocument(texthtml.MIME_TYPE)
        self.writer = texthtml.HTMLWriter(self)

        self.model = None
        self.args = list()

        self.kwargs = dict(context=TestContext())

    def testRenderingArray(self):
        r = Node()
        r.append(Location())
        r.append(Location())
        n = Location()
        r.append(n)
        n.append(Agent())
        n.append(Agent())

        # context = TestContext(('name', ), (n, ))
        # self.kwargs = dict(context=context)
        self.model = NodeModel(r)

    def testRenderingActionForms(self):
        self.model = AgentModel(Agent())

    @defer.inlineCallbacks
    def tearDown(self):
        if not self.model:
            raise SkipTest("Testcase didn't set the model!")
        yield self.writer.write(self.document, self.model,
                                *self.args, **self.kwargs)
        if self.output:
            filename = "%s.html" % (self._testMethodName, )
            with open(filename, 'w') as f:
                print >> f, self.document.get_data()

            static = os.path.join(gateway.__path__[0], 'static')
            dest = os.path.join(os.path.curdir, 'static')
            if not os.path.exists(dest):
                shutil.copytree(static, dest)

        yield common.TestCase.tearDown(self)


class _Base(object):

    def __init__(self):
        pass


class Agent(_Base):

    def __init__(self):
        _Base.__init__(self)
        self.name = str(uuid.uuid1())
        self.status = 'foobar'
        self.count = 10


class Location(_Base):

    def __init__(self):
        _Base.__init__(self)
        self.name = 'hostname'
        self.agents = dict()

    def get_child(self, name):
        return self.agents.get(name)

    def iter_child_names(self):
        return self.agents.iterkeys()

    def append(self, agent):
        self.agents[agent.name] = agent


class Node(_Base):

    def __init__(self):
        _Base.__init__(self)
        self.locations = dict()

    def get_child(self, name):
        return self.locations.get(name)

    def iter_child_names(self):
        return self.locations.iterkeys()

    def append(self, node):
        name = str(uuid.uuid1())
        self.locations[name] = node


@adapter.register(Node, IModel)
class NodeModel(model.Model):

    model.identity('node-model')
    model.collection('locations', getter.source_get('get_child'),
                     call.source_call('iter_child_names'),
                     meta=[('render_array', 3)],
                     desc="Locations or whatever",
                     label='locations')


@adapter.register(Location, IModel)
class LocationModel(model.Model):

    model.identity('location-model')
    model.attribute('name', value.String(), getter.source_attr('name'))
    model.collection('agents', getter.source_get('get_child'),
                     call.source_call('iter_child_names'))


class ShutdownAction(action.Action):

    action.label("Test Action")
    action.desc("Some test action")
    action.value(value.Integer())
    action.result(value.String())
    action.param("toto", value.Integer(), label="Int", desc="Some integer",
                 is_required=False)
    action.param(u"tata", value.String(default="foo"), False)
    action.param("titi", value.Integer(), is_required=False)
    action.param("checkbox1", value.Boolean(default=True))
    action.param("checkbox2", value.Boolean())


class DeleteAction(action.Action):

    action.label("Delete Action")
    action.category(ActionCategory.delete)
    action.desc("Delete the agent")


@adapter.register(Agent, IModel)
class AgentModel(model.Model):

    model.identity('agent-model')
    model.attribute('name', value.String(), getter.source_attr('name'),
                    meta=[('link_owner', True)])
    model.attribute('status', value.String(), getter.source_attr('status'))
    model.attribute('count', value.Integer(), getter.source_attr('count'),
                    setter.source_attr('count'))
    model.action('shutdown', ShutdownAction)
    model.action('delete', DeleteAction)
