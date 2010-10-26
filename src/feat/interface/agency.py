from zope.interface import Interface


class IAdgency(Interface):

    def register_interest(self, factory):
        """
        @param factory: ?
        """