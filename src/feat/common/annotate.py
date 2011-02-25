from feat.common import reflect

_CLASS_ANNOTATIONS_ATTR = "_class_annotations"
_ATTRIBUTE_INJECTIONS_ATTR = "_attribute_injections"
_DEFAULT_ANNOTATION_ORDER = 100


class AnnotationError(Exception):
    pass


class MetaAnnotable(type):

    def __init__(cls, name, bases, dct):
        klasses = [cls] + list(cls.mro())

        # Class Initialization
        method = getattr(cls, "__class__init__", None)
        if method is not None:
            method(name, bases, dct)

        # Attribute Injection
        for k in klasses:
            injections = getattr(k, _ATTRIBUTE_INJECTIONS_ATTR, None)
            if injections is not None:
                for attr, value in injections:
                    setattr(k, attr, value)
                del injections[:]

        # Class Annotations
        for k in klasses:
            annotations = getattr(k, _CLASS_ANNOTATIONS_ATTR, None)
            if annotations is not None:
                for name, methodName, args, kwargs in annotations:
                    method = None
                    for k2 in klasses:
                        method = getattr(k2, methodName, None)
                        if method is not None:
                            break
                    if method is None:
                        raise AnnotationError("Bad annotation %s set on class "
                                              "%s, method %s not found"
                                              % (name, k, methodName))
                    method(*args, **kwargs)
                del annotations[:]

        super(MetaAnnotable, cls).__init__(name, bases, dct)


class Annotable(object):
    __metaclass__ = MetaAnnotable


def injectClassCallback(annotationName, depth, methodName, *args, **kwargs):
    """
    Inject an annotation for a class method to be called
    after class initialization without dealing with metaclass.

    depth parameter specify the stack depth from the class definition.
    """
    locals = reflect.class_locals(depth, annotationName)
    annotations = locals.get(_CLASS_ANNOTATIONS_ATTR, None)
    if annotations is None:
        annotations = list()
        locals[_CLASS_ANNOTATIONS_ATTR] = annotations
    annotation = (annotationName, methodName, args, kwargs)
    annotations.append(annotation)


def injectAttribute(annotationName, depth, attr, value):
    """
    Inject an attribute in a class from it's class frame.
    Use in class annnotation to create methods/properties dynamically
    at class creation time without dealing with metaclass.

    depth parameter specify the stack depth from the class definition.
    """
    locals = reflect.class_locals(depth, annotationName)
    injections = locals.get(_ATTRIBUTE_INJECTIONS_ATTR, None)
    if injections is None:
        injections = list()
        locals[_ATTRIBUTE_INJECTIONS_ATTR] = injections
    injections.append((attr, value))
