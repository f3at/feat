from zope.interface import Interface


class IAgency(Interface):

    def register_interest(self, factory):
        """
        @param factory: ?
        """
