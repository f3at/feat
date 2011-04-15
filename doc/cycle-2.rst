Merging notes
-------------

 - BasePartner.on_goodbye() method changes the mimicry. Change the params of all implemenetation to support this. Should be: ::

      def on_goodbye(self, agent, blackbox):
      	  ...

 - AgencyAgent has a bunch of new usefull methods which makes developers life less miserable. Consider refactoring places where you hacked around problems caused by this things not being there.

   - Breaking execution chain: (call_later, call_next, cancel_delayed_call)

   - Defining and triggering the events: (wait_for_event, callback_event, errback_event)
