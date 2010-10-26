from zope.interface import Interface


class IRequesterFactory(Interface):

    def __call__(agency, agent, requester, *args, **kwargs):
        pass



class IAgencyRequester(Interface):




class IAgentRequester(Interface):
    pass
