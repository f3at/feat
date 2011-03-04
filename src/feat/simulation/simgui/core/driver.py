import glib
import pydot
from twisted.internet import defer

from feat.simulation import driver
from feat.common import manhole

from feat.agents.host import host_agent
from feat.agents.shard import shard_agent
from feat.agents.base import recipient


class GuiParser(manhole.Parser):

    def __init__(self, drv, output, commands, cb_on_finish=None):
        manhole.Parser.__init__(self, drv, output, commands, cb_on_finish)
        self.driver = drv

    def _error_handler(self, f):
        self.driver._set_error(f.getErrorMessage())
        manhole.Parser._error_handler(self, f)


class GuiDriver(driver.Driver):

    def __init__(self):
        driver.Driver.__init__(self)
        self.callbacks = []
        self._parser = GuiParser(
                self,
                self._output,
                self,
                self.finished_processing)

        self.last_error = ''
        self.current_dot = ''

        self.next_update = 2000
        self.min_update = 15000
        self.timer = glib.timeout_add(self.next_update/2, self._timeout_dot)

    def finished_processing(self):
        if self.timer:
            glib.source_remove(self.timer)
            self.timer = 0
        self._timeout_dot()

    def _throw_callbacks(self):
        for callback in self.callbacks:
            callback()

    def _timeout_dot(self):
        dot = export_drv_to_dot(self)
        if self.current_dot != dot:
            self.current_dot = dot
            self._throw_callbacks()
            self.next_update = self.next_update/2
        else:
            self.next_update = round(self.next_update * 1.05)
        if self.next_update < 2000:
            self.next_update = 2000
        if self.next_update > self.min_update:
            self.next_update = self.min_update
        self.timer = glib.timeout_add(int(self.next_update), self._timeout_dot)
        return False

    def on_processed_callback(self, callback):
        self.callbacks.append(callback)

    def _set_error(self, msg):
        self.last_error = msg

    def get_error(self):
        return self.last_error

    def export_to_dot(self):
        return self.current_dot

    def clear(self):
        agents = []
        for ag in self._agencies:
            for a in ag._agents:
                agents.append(a)
        d = defer.DeferredList([a.terminate() for a in agents])
        d.addCallback(lambda _: self._remove_agencies())
        d.addCallback(lambda _: self.finished_processing())
        return d

    def _remove_agencies(self):
        while len(self._agencies):
            del self._agencies[0]


def export_drv_to_dot(drv):
    shards = {}
    edges = []

    cluster_count = 0
    agency_count = 1

    graph = pydot.Graph()
    for agency in drv._agencies:
        agency_name = 'agency %d' %(agency_count)
        agency_dot = pydot.Subgraph(
            graph_name = 'cluster_%d' %(cluster_count),
            label = agency_name,
            style="filled",
            color="lightyellow")
        cluster_count += 1
        agency_count += 1
        agency_added = False
        for agent in agency._agents:
            desc = agent.get_descriptor()
            shard_name = desc.shard
            if shard_name in shards:
                shard_dot = shards[shard_name]
            else:
                shard_dot = pydot.Subgraph(
                        graph_name='cluster_%d' % (cluster_count),
                        style='filled',
                        color='lightblue',
                        label=shard_name)
                shards[shard_name] = shard_dot
                graph.add_subgraph(shard_dot)
                cluster_count += 1
            if not agency_added:
                shard_dot.add_subgraph(agency_dot)
                agency_added = True
            node = pydot.Node(
                    name=str(desc.doc_id),
                    label=agent.log_name,
                    color="white",
                    style="filled",
                    URL='%s' % (desc.doc_id))
            agency_dot.add_node(node)
            for p in desc.partners:
                dst = p.recipient.key
                src = desc.doc_id
                if (src, dst) not in edges and \
                    (dst, src) not in edges:
                        edges.append((src, dst))

    #Finnaly add the edges to graph
    for e in edges:
        edge = pydot.Edge(src=e[0], dst=e[1])
        graph.add_edge(edge)
    return graph.to_string()
