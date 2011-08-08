Merging notes
-------------

* You need to update flumotion-agent script from flumotion-flt repo. It should
  run agency.spawn_agent(agent_id) after constructing standalone agency.
* Also get_cmd_line() static method of standalone agents factory has changed
  mimicry. Now it receives (descriptor, **kwargs).
* All the methods from feat.common.run module has changed its naming convention
  to snake case, to match to convention used in FEAT (update service scripts).
  Also this module no longer adds options on his own (remove run.add_options
  call).
* Agents now remember what resource have been allocated for them by the host
  agent. This should simplify the restart procedure of worker agent. With
  correct implementation of its initiate() and startup() it should be possible
  to change his restart strategy to RestartStrategy.globally (the correct
  allocation will be created).
