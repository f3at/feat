import sys

import gtk

from twisted.internet import reactor

from feat.common import log

from gui import main


def mainloop():
    reactor.run()


def get_controller():
    return Main._main


class Main(log.FluLogKeeper, log.Logger):
    """
    This is the main gui controller
    """
    _main = None

    def __init__(self, core):
        log.FluLogKeeper.__init__(self)
        log.Logger.__init__(self, self)

        self.core = core

        self.builder = gtk.Builder()
        self.builder.add_from_file('data/ui/main.ui')

        self.info('Loading main window...')
        self.main = main.MainWindow(
                self,
                self.builder,
                self.core.driver)

        self.info('Done loading Main window...')
        Main._main = self

    def quit(self):
        gtk.main_quit()
