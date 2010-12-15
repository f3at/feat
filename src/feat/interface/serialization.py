from zope.interface import Interface, Attribute

__all__ = ["IRegistry", "IRestorator", "ISnapshotable", "ISerializable",
           "IInstance", "IReference", "IDereference",
           "IFreezer", "IConverter"]


class IRegistry(Interface):
    '''Register factories to unserialize object.'''

    def register(restorator):
        '''Register L{IRestorer}'''

    def lookup(type_name):
        '''Gives a L{IRestorer} for specified type name
        or None if not found.'''


class IRestorator(Interface):
    '''Knows how to restore a snapshot for a type name.
    Should be registered to a L{IUnserializer}.'''

    type_name = Attribute('')

    def prepare():
        '''Creates and prepares an instance for being recovered.
        It returns an empty instance implementing L{ISerializable}.
        The returned instance's method recover() should be called
        with a snapshot to finish the restoration.
        This methods will create an instance without calling __init__().'''

    def restore(snapshot):
        '''Equivalent of calling prepare() and then the instance
        recover() method with the specified snapshot.'''


class ISnapshotable(Interface):
    '''Only know how to extract a snapshot of its state,
    there is no guarantee of recoverability.'''

    def snapshot():
        '''Called to retrieve the current state of an object.
        It should return only structures of basic python types
        or instances implementing L{ISnapshot}.'''


class ISerializable(ISnapshotable):
    '''Knows how to serialize itself and know it's type name.
    The type name will be used to know which L{IUnserializer}
    to use in order to restore a snapshot.
    When restored, __init__() will not be called on the instance,
    instead recover() will be called with a snapshot.'''

    type_name = Attribute('')

    def recover(snapshot):
        '''Called for the instance to recover its state from a snapshot.
        The mutable values of the snapshot should not be used because
        they may not be initialized yet because of circular references.
        To perform initialization relying on snapshot items being restored
        restored() should be used.
        NOTE: when this method is called __init__() has not been called
        and will never be called, restoration of parent class should be done
        there or in the later call to restored().'''

    def restored():
        '''Called when all unserialized items have been restored.
        WARNING: It doesn't mean all restored() functions have been called.'''


class IInstance(Interface):
    '''Used by some converter to represent ISerializable instances.'''

    type_name = Attribute('Name of the instance type')
    snapshot = Attribute('Snapshot of the instance')


class IReference(Interface):
    '''Used by some converter to represent a reference on a value.'''

    refid = Attribute('Reference identifier')
    value = Attribute('Reference value')


class IDereference(Interface):
    '''Used by some converter to represent a dereference
    of a referenced value.'''

    refid = Attribute('Reference identifier')


class IFreezer(Interface):
    '''Knows how to convert something from a format to another.
    Only knows about basic python types and instances implementing
    L{ISnapshot}. The result of calling freeze() is most probably
    not unserializable. Used for one-way conversion.
    The only guarantee is that multiple call to freeze() will
    have always the same result.'''

    def freeze(data):
        '''One-way converts a format to another format.
        Only work with python basic types and instances implementing
        L{ISnapshotable}. Even if one-way, the result is consistent
        over multiple calls, it gives always the same output for
        the same input.'''


class IConverter(Interface):
    '''Knows how to convert something from a format to another.
    Only knows about basic python types and instances implementing
    L{ISerializable} for which a L{IRestorator} must be registered.
    Converters are normally bidirectional with a serializer and
    an unserializer.'''

    def convert(data):
        '''Converts a format to another format, usually the output
        can be converted back to the original value.
        Only work with python basic types and instances implementing
        L{ISerializable}. The result is consistent over multiple calls,
        it gives always the same output for the same input.'''
