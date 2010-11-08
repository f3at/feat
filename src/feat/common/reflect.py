import types


def canonical_name(obj):
    global _canonical_lookup
    return _canonical_lookup.get(type(obj), _canonical_default)(obj)


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

