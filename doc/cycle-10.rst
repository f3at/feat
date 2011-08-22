Merging notes
-------------

* Recipient's shard property is deprecated, please use the route property.
* To copy a message use duplicate() method not clone().
* Emulation agency's initate() method signature changed.
  Because it can accept multiple messaging backend, the messaging
  parameter has been moved to the end.
  Use initiate(db, journal, mesg) instead of initate(mesg, db, journal).
* Port allocator has been removed. Now ports should be reserved as part of allocation (with (pre)allocate, release, premodify) methods. First in HostDef now includes 'port_ranges' dict (format name -> (first, last)). These names can be used to reserve ports, so if there is resource names *streamer_ports* the line: ::

   state.resource.allocate('streamer_ports', 4)

would generate an allocation with 4 ports from the range. Naturaly this works exactly the same as already known resource, so for agents which needs specific ports (like manager agent) it would make sense to put this information as a attribute of IAgentFactory (resource).

Also in previous sprint the allocation used by the agent is storend in his own descriptor, so if this allocation.id has been passed to HostAgent.start_agent() command, this agent can get information about the ports allocated for him with: ::

    desc = state.medium.get_descriptor()
    ports = desc.resource['streamer_ports'].values
