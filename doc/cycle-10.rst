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
* The service and startup scripts has been all moved from FLT to FEAT. All feat related config is now stored in /etc/feat/feat.ini file. FLT package should now store it's config in /etc/feat/flt.ini, the config should look somewhat like this: ::

    [Feat]
    import: flt.everything
    agent: happy_agent

To make it being loaded you need to include a line in feat.ini: ::

    [Feat]
    config-file: /etc/feat/flt.ini

Following executables should be removed from FLT:
- dbload - to prepare the database one should run *feat-dbload -C /etc/feat/feat.ini*
- service.py - to start service you may use *feat-service {start|stop|restart}* or init scripts.
- init scripts (feat provides it, name of service is feat)

From now on, by default feat uses logdir: /var/log/feat, and rundir: /var/run/feat. It runs as the user flumotion, so you would have to investigate issues with flumotion-agent not starting without super privileges.

* Feat gateway is now forced to use SSL, if no PKCS12 is passed with command line argument "-G",
  the gateway will be disabled. For development purpose, the file "conf/gateway.p12" can be used for the server,
  and "conf/dummy.p12" for clients, the client PKCS12 should be imported in the web browser.

* If really needed the gateway can be forced to use normal UNSECURE HTTP, for this pass the command line argument --allow-tcp-gateway.

* To enable the tunneling backend SSL certificate and key must be provided as a PKCS12 through the command line parameter "-T".
  If not provided the tunneling backend will be disabled. For development purpose the file "conf/tunneling.p12" can be used.
