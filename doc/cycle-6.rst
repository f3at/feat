Merging notes
-------------

1. Rename IAgent.killed -> on_killed. This was not consistent with the naming we use.

2. IAgent methods:
   - initiate(),
   - startup(),
   - on_disconnect(),
   - on_reconnect(),
   - on_killed(),
   - shutdown()
are now called by machinery analizing mro, which means that you should remove all the super-class calls from these methods (or they would be called multiple times).
**IMPORTANT**: This means that all usages of notifier, rpc, resources, etc should not be initialized anymore.

3. Remove calls of BaseAgent.initiate_partners() method. It is now called by the base class and it has been renamed not to create confusion.

4. Partners use MRO calls as well. This means that from any partner callback (initiate, on_shutdown, on_goodbye, etc..) you should not call the super class method. It will be handled by some black magic.
**IMPORTANT**: MRO calls uses parameter names of the method to figure out which parameters to pass. All the names must by uniformed. Take a look at feat.agents.base.partners.BasePartner class for the correct
argument names. The good side is that you don't have to care about the order of parameters. Also there is no need to specify the argument which is not used by the function.



