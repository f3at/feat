from zope.interface import Interface, Attribute


class IRegistry(Interface):
    '''Register factories to unserialize object.'''

    def register(restorator):
        '''Register L{IRestorer}'''


class IRestorator(Interface):
    '''Knows how to restore a snapshot for a type name.
    Should be registered to a L{IUnserializer}.'''

    type_name = Attribute()

    def restore(snapshot):
        pass


class ISerializable(Interface):
    '''Knows how to serialize itself and know it's type name.
    The type name will be used to know which L{IUnserializer}
    to use in order to restore a snapshot.
    When restored, __init__() will not be called on the instance,
    instead __restore__() will be called with a snapshot.'''

    type_name = Attribute()

    def __restore__(snapshot, context):
        pass

    def snapshot(context):
        '''Called to retrieve the current state of an object.
        It should return only structures of basic python types
        or instances implementing L{ISerializable}.'''


class ISerializer(Interface):
    '''Knows how to convert an object to bytes.'''

    def serialize(obj, context={}):
        pass


class IUnserializer(Interface):
    '''Knows how to convert bytes to object.
    A L{IRestorator} must be registered for any types other
    than python basic types.
    '''

    def unserialize(data, context={}):
        pass


class IFormater(Interface):
    '''Knows how to convert s-expression to bytes'''

    def format(data):
        pass


class IParser(Interface):
    '''Knows how to convert bytes to s-expression'''

    def parse(data):
        pass
