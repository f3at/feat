import gtk
import re


class HelpAgent(object):

    def __init__(self, parent):
        self.builder = gtk.Builder()
        self.builder.add_from_file('data/ui/help-agent.ui')

        self.window = self.builder.get_object('help_agent_dialog')
        self.window.set_transient_for(parent)
        self.window.set_position(gtk.WIN_POS_CENTER_ON_PARENT)
        self.window.connect('delete-event', lambda *e: self.close())

        self.close_button = self.builder.get_object('close_button')
        self.close_button.connect('clicked', lambda *e: self.close())

        self.model = self.builder.get_object('model')

    def close(self):
        self.window.hide()
        self.window.destroy()

    def add_help(self, msg):
        self.model.clear()
        items = [re.sub('\s{2,}', '\t', i).split('\t')
                for i in msg.split('\n')]
        for item in items:
            self.model.append(item)

    def run(self):
        self.window.show_all()
