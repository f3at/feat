========================
Using FEAT as DNS server
========================

The purpose of this document is to demonstrate how FEAT framework can be used as a DNS server or at least it's frontend. You may wonder Why would anybody do that. The gain here is that FEAT makes it easy to create nice self documented external REST API. The way you may want to use it is to make API calls from your application to programaticly create/remove dns entries. Those who ever maintained the zone files of bind9 server will apprieciate this nice frontend. It's important to stress that this is just a tiny piece of the frameworks functionality.

Before reading this you should be familiar with the basis of how DNS protocol works. You should know what dns zones are, and what zone transfer is. It'd also help a lot if you already had some experience with configuring bind9 server. Nevertheless the necessary steps will be discussed.

Configuring zone transfer
=========================

The way we normally use dns agent on our production cluster is that we run a single instance which listents to notifications sent by agents of different kind. After any change in the zone the agent sends the notifications to its slaves, and so that they know they need to update their entries. The dns queries are *not* resolved by the dns agent himself, they are handled by the bind servers. The only reason we use it like this, is that our sysadmin team is familiar with this particular server. Long before we created FEAT they were already managing dns zones and there are some smart things they do related to fail safety, security etc, which I have only vouge knowledge about, therefore will not discuss.


Using external API
==================

The external api is served as part of the FEAT gateway. In simple words every FEAT process listens to HTTP connections. Most of important component have their URLs defined. If the component is running in the different process than the one handling the request, the redirect is rendered. This is really handy because you don't need to care where things are running. However the price is that the applications using gateway need to support post-through-redirect.

---------
Api calls
---------

Managing running servers.
-------------------------

* GET /api/dns/servers. List of running dns servers. The list includes information about the hosts the agents runs on and ports they listen.

* POST /api/dns/servers. Configure the new dns server. Fields of JSON body:
 - suffix: The suffix of the zone. Only this field is mandatory.
 - slaves: List of slave servers to notify. Format 'ip1:port, ip2:port'
 - ns: The nameservers name,
 - refresh: Number of seconds the zone should be refreshed,
 - retry: Interval before failed refresh should be retried,
 - expire: Upper limit on time interval before expiry,
 - minimum: Minimum TTL,

* DELETE /api/dns/servers/<agent_id>. Shutdown the agent with given ID.

Managing entries.
-----------------

* GET /api/dns/entries/<suffix>. Get the list of names registered in the zone.

* GET /api/dns/entries/<suffix>/<name>. Get the list of entries for the name.

* POST /api/dns/entries/<suffix>. Create DNS entry. Field of JSON body:
 - prefix: Prefix of the entry.
 - type: Entry type. Can be 'record_A' or 'record_CNAME'.
 - entry: IP adress in case of record_A. In case of record_CNAME the name to alias.

* DELETE /api/dns/entries/<suffix>/<name>/<entry>. Remove dns entry or alias.
