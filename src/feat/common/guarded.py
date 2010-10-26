import sys


class MetaGuarded(type):

    def __init__(cls, name, bases, dct):
        print "MetaGuarded.__init__(%s, %s, %s, %s)" % (cls, name, bases, dct)
        super(MetaGuarded, cls).__init__(name, bases, dct)


class Guarded(object):
    __metaclass__ = MetaGuarded


class State(object):
    pass


# Decorators

def mutable():
    pass

def immutable():
    pass


## Private ##

def _getClassLocals(tag, depth=3):
    frame = sys._getframe(depth)
    locals = frame.f_locals
    # Try to make sure we were called from a class def. In 2.2.0 we can't
    # check for __module__ since it doesn't seem to be added to the locals
    # until later on.  (Copied From zope.interfaces.declartion._implements)
    if (locals is frame.f_globals) or (
        ('__module__' not in locals) and sys.version_info[:3] > (2, 2, 0)):
        raise TypeError(tag + " can be used only from a class definition.")
    return locals
