Merging notes
-------------

1. Fiber and deferred related changes:

	- fiber.drop_result, fiber.bridge_result, defer.drop_result
	  and defer.bridge_result are now deprecated, please use the equivalent
	  functions drop_param and bridge_param.

	- new utility functions have been added to defer and fiber module:

		call_param: call a method on the received parameter.
		            For example:
					  f.add_callback(fiber.call_param, "spam", 42)
					  f.succeed(self)
					Will end up calling:
					  self.spam(42)

		inject_param: call a method and inject the received parameter at
		              the specified position.
		              For example:
		              	f.add_callback(fiber.inject_param, 1, self.spam, 1, 2)
					  	f.succeed(3)
					  Will end up calling:
					    self.spam(1, 3, 2)

		debug: log specified parameters.
		       For example:
		         f.add_callback(fiber.debug, "Spam %s", 42)
		       Will end up logging:
		       	 DEBUG [XXX] "debug" fiber May 10 13:21:07 Spam 42 (XXX:XX)

		trace: log specified parameters alongside the received parameter.
		       For example:
		         f.add_callback(fiber.trace, "Spam %s", 42)
		         f.succeed(18)
		       Will end up logging:
		       	 DEBUG [XXX] "debug" fiber May 10 13:21:07 Spam 42: 18 (XXX:XX)

	- By setting the environment variable FEAT_TRACE_FIBERS to 1, every method
	  call done by the fibers will be logged taking into account the special
	  helper function in fiber module.
	  For example:
	  	f = fiber.succeed(1)
	  	f.add_callback(self.spam, 'A')
	  	f.add_callback(fiber.override_result, 2)
	  	f.add_callback(fiber.drop_param, self.bacon, 'B')
	  	f.add_callback(fiber.override_result, self)
	  	f.add_callback(fiber.call_param, "eggs", 'C')
	  	f.add_callback(fiber.override_result, 3)
	  	f.add_callback(fiber.inject_param, 1, "beans", 'D')
	  Will log:
	    DEBUG [XXX] "FIBER_ID" fiber module.Class.spam(1, 'A') (module.py:XX)
	    DEBUG [XXX] "FIBER_ID" fiber module.Class.bacon('B') (module.py:XX)
	    DEBUG [XXX] "FIBER_ID" fiber module.Class.eggs('C') (module.py:XX)
	    DEBUG [XXX] "FIBER_ID" fiber module.Class.beans('D', 3) (module.py:XX)

	- All agents startup() methods should call agent.BaseAgent.startup(self).

2. Deprecation in Tasks:
    When calling task's medium, AgencyTask.finish() got deprecated,
    use AgencyTask.terminate() instead.

3. Calling wait_for_listeners_finish() on agent's medium is deprecated,
   use  wait_for_protocols_finish() instead.

4. In agent code Partners class should inherit from agent.Partners and partners
   should inherit from agent.BasePartner. partners.Partners and
   partners.BasePartner SHOULD NOT BE USED ANYMORE.

5. BE SURE to call initiate_partners inside your agent initiate method.

6. A first basic version of REST API for the agent cluster has been added.
   To use it just connect to the port 7777 of a machine running feat with
   a web browser. For now it only shows basic information but navigation
   between agencies is already supported.
