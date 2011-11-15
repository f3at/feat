import uuid

# from zope.interface import implements

from twisted.trial.unittest import SkipTest

from feat.common import defer, adapter
from feat.test import common
from feat.models import texthtml, model, action, value, call, getter, setter
from feat.web import document

from feat.models.interface import IModel, IAspect


class HTMLWriterTest(common.TestCase):

    output = True

    @defer.inlineCallbacks
    def setUp(self):
        yield common.TestCase.setUp(self)
        self.document = document.WritableDocument(texthtml.MIME_TYPE)
        self.writer = texthtml.HTMLWriter(self)

        self.model = None
        self.args = list()
        self.kwargs = dict()

    def testRenderingDummyModel(self):
        r = Node()
        r.append(Location())
        r.append(Location())
        n = Location()
        r.append(n)
        n.append(Agent())
        n.append(Agent())

        self.model = NodeModel(r)

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
    model.childs('locations', getter.source_get('get_child'),
                 call.source_call('iter_child_names'),
                 meta=[('render_array', 3)])


# class LocationCollection(model.Collection):

#     model.identity('loc-collection')
#     model.child_names(call.source_call('iter_child_names'))
#     model.child_source(getter.source_get('get_child'))
#     model.meta('render_array', 3)


@adapter.register(Location, IModel)
class LocationModel(model.Model):

    model.identity('location-model')
    model.attribute('name', value.String(), getter.source_attr('name'))
    model.childs('agents', getter.source_get('get_child'),
                 call.source_call('iter_child_names'))


@adapter.register(Agent, IModel)
class AgentModel(model.Model):

    model.identity('agent-model')
    model.attribute('name', value.String(), getter.source_attr('name'))
    model.attribute('status', value.String(), getter.source_attr('status'))
    model.attribute('count', value.Integer(), getter.source_attr('count'))
