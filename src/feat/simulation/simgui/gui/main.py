import sys
import gettext
_ = gettext.gettext

import gtk
import glib

import pydot

from gui import command, errors, menu, agentinfo, agentview
from gui.dlg import help_agent
from feat.extern import xdot
from core import settings


class MainWindow(object):
    """
    This is the main window.
    """

    def __init__(self, controller, builder, driver):
        self.controller = controller
        self.builder = builder
        self.driver = driver
        self.driver.on_processed_callback(self._on_script_processed)
        self.window = builder.get_object('MessiWindow')

        self.window.set_title('simulator')
        self.window.connect('destroy', lambda *e: self.quit())

        self.command = command.Command(self.window, self.builder, self.driver)
        self.errors = errors.Error(self.builder, self.driver)

        self.agent_info = agentinfo.AgentInfo(self.builder)

        self.xdot = xdot.DotWidget()
        container = self.builder.get_object('xdot_container')
        container.pack_start(self.xdot)

        self.menu_items = {}
        self.menu_agents_filter = gtk.Menu()
        agentview.setup_menu(self.menu_agents_filter, self.menu_items)
        for key, item in self.menu_items.iteritems():
            item.connect('activate', self._change_agents_filter, (key, ))
        self.menu_agents_filter.show_all()

        self._setup_toolbar()
        self._setup_menuitem()

        #splitter
        self.hsplitter = builder.get_object('hsplitter')
        self.vsplitter = builder.get_object('vsplitter')

        self._setup_position()
        self._connect_events()

    def _connect_events(self):
        self.vsplitter.connect('notify::position', self._configure_event)
        self.hsplitter.connect('notify::position', self._configure_event)
        self.window.connect('configure_event', self._configure_event)

        self.xdot.connect('clicked', lambda widget, url, event:
                self._agent_clicked(url))

        self.xdot.connect('show-menu', lambda widget, url, event:
                self._agent_show_menu(url, event))
        self.xdot.connect('show-global-menu', lambda widget, event:
                self._show_agents_filter(event))

    def _setup_toolbar(self):
        reset = self.builder.get_object('reset_toolbar')
        reset.connect('clicked', self.reset_toolbar_clicked)

        reload = self.builder.get_object('reload_toolbar')
        reload.connect('clicked', self.reload_toolbar_clicked)

        zoom_in = self.builder.get_object('zoomin_button')
        zoom_in.connect('clicked', self.xdot.on_zoom_in)

        zoom_out = self.builder.get_object('zoomout_button')
        zoom_out.connect('clicked', self.xdot.on_zoom_out)

        zoom_reset = self.builder.get_object('zoomreset_button')
        zoom_reset.connect('clicked', self.xdot.on_zoom_100)

    def _setup_menuitem(self):
        zoom_in = self.builder.get_object('zoomin_menuitem')
        zoom_in.connect('activate', self.xdot.on_zoom_in)

        zoom_out = self.builder.get_object('zoomout_menuitem')
        zoom_out.connect('activate', self.xdot.on_zoom_out)

        zoom_reset = self.builder.get_object('zoomreset_menuitem')
        zoom_reset.connect('activate', self.xdot.on_zoom_100)

        reset = self.builder.get_object('driverreset_menuitem')
        reset.connect('activate', self.reset_toolbar_clicked)

        reload = self.builder.get_object('driverreload_menuitem')
        reload.connect('activate', self.reload_toolbar_clicked)

        quit = self.builder.get_object('quit_menuitem')
        quit.connect('activate', lambda _: self.quit())

    def _setup_position(self):
        """
        Setup the position and sized
        """

        width = settings.get_int_option('gui/mainw_width', 1000)
        height = settings.get_int_option('gui/mainw_height', 600)
        x = settings.get_int_option('gui/mainw_x', 10)
        y = settings.get_int_option('gui/mainw_y', 10)

        self.window.move(x, y)
        self.window.resize(width, height)

        pos = settings.get_int_option('gui/hsplitter', 400)
        self.hsplitter.set_position(pos)
        pos = settings.get_int_option('gui/vsplitter', 700)
        self.vsplitter.set_position(pos)

    def _configure_event(self, *e):
        pos = self.hsplitter.get_position()
        if pos != settings.get_int_option('gui/hsplitter', -1):
            settings.set_option('gui/hsplitter', pos)

        pos = self.vsplitter.get_position()
        if pos != settings.get_int_option('gui/vsplitter', -1):
            settings.set_option('gui/vsplitter', pos)

        (width, height) = self.window.get_size()
        if [width, height] != [settings.get_int_option("gui/mainw_"+key, -1) \
                for key in ["width", "height"]]:
            settings.set_option('gui/mainw_height', height)
            settings.set_option('gui/mainw_width', width)
        (x, y) = self.window.get_position()
        if [x, y] != [settings.get_int_option("gui/mainw_"+key, -1) for \
                key in ["x", "y"]]:
            settings.set_option('gui/mainw_x', x)
            settings.set_option('gui/mainw_y', y)

        return False

    def _update_xdot(self):
        dotcode = self.driver.export_to_dot()
        self.xdot.set_dotcode(dotcode)

    def _agent_clicked(self, agent_id):
        self.agent_info.clear()
        agent = self.driver.find_agent(agent_id)
        self.agent_info.load(agent.get_agent(), None)
        self.agent_info.load(agent.get_descriptor(), None)

    def _agent_show_menu(self, agent_id, event):
        agent_menu = menu.AgentMenu(agent_id)
        agent_menu.connect('terminate-agent', self._on_terminate_agent)
        agent_menu.connect('help-agent', self._on_help_agent)
        agent_menu.popup(event)

    def _show_agents_filter(self, event):
        self.menu_agents_filter.popup(None, None, None,
                event.button, event.time)

    def _change_agents_filter(self, item, key):
        if not item.get_active():
            self.driver.add_filter(key[0])
        else:
            self.driver.remove_filter(key[0])
        self._update_xdot()

    def _on_terminate_agent(self, menu, agent_id):
        agent = self.driver.find_agent(agent_id)
        d = agent.terminate()
        d.addCallback(lambda _: self._on_script_processed())

    def _on_help_agent(self, menu, agent_id):
        agent = self.driver.find_agent(agent_id)
        self.help_agent_dlg = help_agent.HelpAgent(self.window)
        self.help_agent_dlg.add_help(agent.help())
        self.help_agent_dlg.run()

    def _on_script_processed(self):
        self._update_xdot()

    def reset_toolbar_clicked(self, button):
        dlg = gtk.MessageDialog(self.window,
                gtk.DIALOG_DESTROY_WITH_PARENT, gtk.MESSAGE_QUESTION,
                gtk.BUTTONS_YES_NO,
                _('All agents will be terminated. Do you want continue?'))
        if dlg.run() == gtk.RESPONSE_YES:
            self.driver.clear()
            self.agent_info.clear()
        dlg.destroy()

    def reload_toolbar_clicked(self, button):
        self._update_xdot()

    def quit(self):
        self.window.hide()
        self.controller.quit()
