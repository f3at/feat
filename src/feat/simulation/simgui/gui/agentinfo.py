import gtk

from feat.agents.base import agent

from core import guistate, settings
from feat.common import log


class AgentInfo(object):
    """ Show information about selected agent """

    def __init__(self, builder):
        self.builder = builder
        self.model = gtk.TreeStore(str, str)
        self.view = self.builder.get_object('agent_state_view')
        self.view.set_model(self.model)

        self._setup_columns()

    def clear(self):
        self.model.clear()

    def _setup_columns(self):
        columns = self.view.get_columns()
        for col in columns:
            col.connect('notify::width', self.set_column_width)
            name = 'gui/col_width_%s' % (col.get_title())
            width = settings.get_int_option(name, 200)
            col.set_sizing(gtk.TREE_VIEW_COLUMN_FIXED)
            col.set_resizable(True)
            col.set_fixed_width(width)

    def set_column_width(self, col, *e):
        name = 'gui/col_width_%s' % (col.get_title())
        w = col.get_width()
        if w != settings.get_int_option(name, -1):
            settings.set_option(name, w)

    def load(self, obj, parent, name=None):
        try:
            parse = guistate.IGuiState(obj)
            if name is None:
                name = parse.get_name()
            else:
                name = [name, None]
            node = self.model.append(parent, name)
            for e in parse.iter_elements():
                self.load(e[1], node, e[0])
            self.view.expand_row(self.model.get_path(node), True)
        except TypeError as e:
            log.info('agent-info', 'Error adapting: %r', e)
