import os
import sys

from twisted.internet import gtk2reactor
gtk2reactor.install()

basedir = os.path.dirname(os.path.realpath(__file__))
if not os.path.exists(os.path.join(basedir, "sim.py")):
    cwd = os.getcwd()
    if os.path.exists(os.path.join(basedir, "sim.py")):
        basedir = cwd
sys.path.insert(0, basedir)
sys.path.insert(0, os.path.join(basedir, '../../../'))


def main():
    from core import main
    sim = main.Sim()

if __name__ == '__main__':
    main()
