from zope.interface import Interface


class IJournalKeeper(Interface):

    def journal_entry():
        """To be defined"""
