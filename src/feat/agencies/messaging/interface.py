from zope.interface import Interface, Attribute


class ISink(Interface):
    '''
    Interface implemented by varios elements of the routing chain.
    Object implementing it can receive messages.
    '''

    def on_message(message):
        '''
        Called when the message comes in.
        @param message: L{feat.agents.base.message.BaseMessage}
        '''


class IChannel(Interface):
    '''
    Interface used by L{IAgencyAgent} to send messages and maintain bindings.
    '''

    def post(recipients, message):
        '''
        Send message to a recipients.

        @param recipients: IRecipients to send the message to.
        @param message: Message body.
        @type message: subclass of L{feat.agents.message.BaseMessage}
        '''

    def release():
        '''
        Cleanup and disconnect client from messaging module.
        '''

    def create_binding(recipient):
        '''
        Creates a binding, makes agent start receiving messages from the
        given recipient.

        @param recipient: IRecipient we will be available on.
        '''

    def get_bindings(route):
        '''
        Returns the list of address to which agent is bound.

        @param route: Optional. If specified limits the result to the selected
                      shard. If None return all.

        @returns: List of IRecipient.
        @rtype:   list
        '''


class IChannelBinding(Interface):

    recipient = Attribute('Recipient to which I bind')
    route = Attribute('Route for the binding')


class IBackend(Interface):

    channel_type = Attribute("Channel name.")

    def initiate(self):
        """
        Called after backend is added.
        @return: Deferred fired when the initialization is completed.
        """

    def is_idle(self):
        """Returns if the backend is idle."""

    def is_connected():
        """Returns the backend is connected."""

    def wait_connected():
        """returns a Deferred fired when the backend got connected."""

    def disconnect():
        """Disonnect the backend."""

    def add_disconnected_cb(fun):
        """Register a function to be called
        when the backend got disconnected."""

    def add_reconnected_cb(fun):
        """Register a function to be called
        when the backend got disconnected."""

    def binding_created(binding):
        '''
        Callback called when one of channels creates a internal binding.
        @param binding: IChannelBinding
        '''

    def binding_removed(binding):
        '''
        Callback called when one of channels removes an internal binding.
        @param binding: IChannelBinding
        '''

    def create_external_route(backend_id, **kwargs):
        '''
        Callback called on all the backends when agent creates the external
        route.
        @return: C{bool} flag saying if the backend took any action
        '''

    def remove_external_route(backend_id, **kwargs):
        '''
        Callback called on all the backends when agent removes the external
        route.
        @return: C{bool} flag saying if the backend took any action
        '''


class ITunnelBackend(Interface):
    '''
    Interface implemented by the tunneling backend (network/emu) used by
    the Tunneling IBackend implementation.
    '''

    def connect(tunneling):
        '''
        Called on initialization of the module to bind the reference to the
        Tunneling module (the one providing IBackend to messaging).
        '''

    def disconnect():
        '''
        Called during the cleanup.
        '''

    def add_route(recipient, uri):
        '''
        Open connection to uri and route message to recp through it.
        '''

    def remove_route(recipient):
        '''
        Close connection to agent identified by recp.
        '''


class IMessagingClient(Interface):

    def define_exchange(name, exchange_type=None):
        pass

    def define_queue(name):
        pass

    def publish(key, shard, message):
        pass

    def create_binding(exchange, queue, key=None):
        pass

    def delete_binding(exchange, queue, key=None):
        pass
