from zope.interface import Interface

import logging, journaling


class IAgentFactory(Interface):

    def __call__(agency, *args, **kwargs):
        pass


class IAdgencyAgent(logging.ILogger, journaling.IJournalKeeper):

    def register(factory, *args, **kwargs):
        pass

    def revoke(factory, *args, **kwargs):
        pass

    def initiate(factory, *args, **kwargs):
        pass


class IAgent(Interface):

    def initiate():
        pass

    def snapshot():
        pass


