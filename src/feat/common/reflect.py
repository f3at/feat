import sys
import types


def canonical_name(obj):
    if isinstance(obj, types.MethodType):
        return _canonical_method(obj)

    if isinstance(obj, (type, types.FunctionType)):
        return _canonical_type(obj)

    if isinstance(obj, types.NoneType):
        return _canonical_none(obj)

    if isinstance(obj, types.BuiltinFunctionType):
        return _canonical_builtin(obj)

    return _canonical_type(obj.__class__)


def class_locals(depth, tag=None):
    frame = sys._getframe(depth)
    locals = frame.f_locals
    # Try to make sure we were called from a class def. In 2.2.0 we can't
    # check for __module__ since it doesn't seem to be added to the locals
    # until later on.  (Copied From zope.interfaces.declartion._implements)
    if (locals is frame.f_globals) or (
        ('__module__' not in locals) and sys.version_info[:3] > (2, 2, 0)):
        name = (tag and tag + " ") or ""
        raise TypeError(name + "can be used only from a class definition.")
    return locals


def inside_class_definition(depth):
    frame = sys._getframe(depth)
    locals = frame.f_locals
    # Try to make sure we were called from a class def. In 2.2.0 we can't
    # check for __module__ since it doesn't seem to be added to the locals
    # until later on.  (Copied From zope.interfaces.declartion._implements)
    if ((locals is frame.f_globals)
        or (('__module__' not in locals)
            and sys.version_info[:3] > (2, 2, 0))):
        return False
    return True


### Private Methods ###


def _canonical_type(obj):
    return obj.__module__ + "." + obj.__name__


def _canonical_none(obj):
    return None


def _canonical_method(obj):
    return _canonical_type(obj.im_class) + "." + obj.__name__


def _canonical_builtin(obj):
    return "__builtin__." + obj.__name__
