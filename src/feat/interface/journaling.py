from zope.interface import Interface


class IJournalKeeper(Interface):
    '''Store journal entries'''

    def do_journal():
        """To be defined"""


class IJournaler(Interface):
    pass
