from zope.interface import Interface


class IJournalKeeper(Interface):
    '''Store journal entries'''

    def journal_entry():
        """To be defined"""
