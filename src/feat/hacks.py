# -*- Mode: Python -*-
# vi:si:et:sw=4:sts=4:ts=4


"""
Because Flumotion is depending heavily on ihooks and relative imports
are not supported in python 2.6 implementation of ihook, it is not possible
to import a root module with the same name as the current module.
This is a probleme for feat's json module because it needs to import
the root json module. This function just import it from inside another
pacakge.
"""


def import_json():
    import json
    return json


def import_time():
    import time
    return time


def import_signal():
    import signal
    return signal
