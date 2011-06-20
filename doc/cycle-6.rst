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




