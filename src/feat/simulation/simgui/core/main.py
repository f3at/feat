import os
import sys

from feat.common import log

from core import driver


class Sim(log.FluLogKeeper, log.Logger):

    _sim = None

    def __init__(self):
        log.FluLogKeeper.__init__(self)
        log.Logger.__init__(self, self)
        self.setup_logging()

        self._init()

        #Run the GUI mainloop
        import gui
        gui.mainloop()

    def _init(self):

        #load driver
        self.driver = driver.GuiDriver()

        #Setup GUI
        self.gui = None
        import gui
        self.gui = gui.Main(self)
        self.gui.main.window.show_all()

        Sim._sim = self

    def quit(self):
        logging.info('Shuting down...')
        if self.gui:
            self.gui.quit()

    def setup_logging(self):
        log.FluLogKeeper.init()
        log.FluLogKeeper.set_debug("*:5")


def sim():
    if not Sim._sim:
        raise AttributeError(_('Simulation is not yet finished loading'))
    return Sim._sim
