import sys
import types


def canonical_name(obj):
    global _canonical_lookup
    return _canonical_lookup.get(type(obj), _canonical_default)(obj)


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


def _canonical_default(obj):
    return _canonical_class(obj.__class__)


def _canonical_class(obj):
    return obj.__module__ + "." + obj.__name__


def _canonical_none(obj):
    return None


def _canonical_method(obj):
    return _canonical_class(obj.im_class) + "." + obj.__name__


def _canonical_builtin(obj):
    return "__builtin__." + obj.__name__


def _canonical_function(obj):
    return obj.__module__ + "." + obj.__name__

_canonical_lookup = {types.TypeType: _canonical_class,
                     types.NoneType: _canonical_none,
                     types.MethodType: _canonical_method,
                     types.FunctionType: _canonical_class,
                     types.BuiltinFunctionType: _canonical_builtin}
