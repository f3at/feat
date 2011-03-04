import gtk

from core import history
from gui import command_history


class Command(object):
    """
        The command panel
    """

    def __init__(self, window, builder, driver):
        self.builder = builder
        self.window = window

        self.editor = self.builder.get_object('command_editor')
        textbuffer = self.editor.get_buffer()
        textbuffer.set_text("""agency = spawn_agency()
shard_desc = descriptor_factory('shard_agent', 'root')
host_desc = descriptor_factory('host_agent')
agency.start_agent(shard_desc)
agency.start_agent(host_desc)
""")

        textbuffer.connect('changed', self.on_text_changed)

        self.run_button = self.builder.get_object('run_button')
        self.run_button.connect('clicked', self.on_run_clicked)

        self.clear_button = self.builder.get_object('clear_button')
        self.clear_button.connect('clicked', self.on_clear_clicked)

        self.history_button = self.builder.get_object('history_button')
        self.history_button.connect('clicked', self.on_history_clicked)

        self.driver = driver
        self.driver.on_processed_callback(self._on_script_processed)

        self.history = history.HistoryLogger()

    def on_run_clicked(self, button):
        textbuffer = self.editor.get_buffer()
        script = textbuffer.get_text(
                textbuffer.get_start_iter(),
                textbuffer.get_end_iter())
        self.driver.process(script)
        #self.run_button.set_sensitive(False)
        self.history.append_command(script)

    def _on_script_processed(self):
        if self.run_button.get_sensitive() == False:
            self.run_button.set_sensitive(True)

    def on_clear_clicked(self, button):
        textbuffer = self.editor.get_buffer()
        textbuffer.set_text('')

    def on_text_changed(self, textbuffer):
        count = textbuffer.get_char_count()
        self.run_button.set_sensitive(count)
        self.clear_button.set_sensitive(count)

    def on_history_clicked(self, button):
        self.history_dlg = command_history.CommandHistory(
                self.window,
                self.history)
        self.history_dlg.run()
