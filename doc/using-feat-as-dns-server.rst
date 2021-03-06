:Author: Marek Kowalski
:Contacts: kowalski0123 (at) gmail.com


========================
Using FEAT as DNS server
========================

The purpose of this document is to demonstrate how FEAT framework can be used as a DNS server or at least it's frontend. You may wonder why would anybody do that. The gain here is that FEAT makes it easy to create nice self documented external REST API. So we have created one to manage dns entries. The way you may want to use it is to make API calls from your application to create/remove dns entries. Those who have ever maintained the zone files of the bind9 server will apprieciate the simplicity of this frontend. This tutorial is ment to show one of many functionalities of the framework, it's not its key purpose, nor the significant part.

Before reading this you should be familiar with the basis of the dns protocol. You should know what dns zones are, and what zone transfer is. It'd also help a lot if you have already had some experience with configuring named server. Nevertheless the necessary steps will be discussed.


Configuring the named server
============================
Before starting looking at setting up FEAT lets configure the bind9 server. Our use case is that we have a cluster consisting of many nodes. We select a couple of them as being capable of running the dns servers. We need to know the ip addresses of these nodes beforehand as we will have to list them in the configuration of named server. If however your cluster will consist from one node only there is nothing to think about.
For following section lets assume that we will be running a single dns server on the port 5000 with ip *172.17.5.52*.

-------------
Zone transfer
-------------
The way we set up the dns agent in our production cluster is that we run a single instance which listens to the notifications sent by all kinds of agents. After every change in the zone the dns agent sends the OP_NOTIFY messages to its slaves, so that they know they need to update their zones. The slaves are named servers, the dns queries are *never* resolved by the dns agent itself. The reason we use this setup is that it makes us feel more confident in terms of being secured against the DOS attacks. And we have an experienced sysadmin team managing this for us.

To set this up the following parts on *named.conf* should be changed: ::

    options {
    	.......
        allow-transfer { secondary; };
        notify yes;
	.......
    };

    zone "service.flt.fluendo.lan" {
        type slave;
        masters {172.17.5.52 port 5000;};
        file "service.flt.fluendo.lan.zone";
        allow-notify {172.17.5.52;};
    };


Configuring FEAT
================
In this section we will install and configure feat running on a single host. If these are your first steps with feat refer the `Introduction to feat <https://github.com/downloads/f3at/feat/introduction_to_feat.pdf>`_ article. You will find there the instructions on deploying the CouchDB database and running the service. In our case we can skip the part with RabbitMQ server. This would be necessary however if you'd like to use more than one host.

The only specific part in our case are setting in *feat.ini* file. We need to add: ::

     host-category: address:fixed
     host-ports-ranges: dns:5000:5000

The first line defines that the IP address of the host is fixed. It is the requirement for running the dns agent. The second line defines the port resource with values from the range 5000-5000. This will be a listening port for the dns server. This will allow running a single dns agent, you can make the range wider if you need to handle more zones.


Using external API
==================

The external api is served as part of the FEAT gateway. In simple words every FEAT process listens to HTTP connections. The most of important component have their URLs defined. If the component is running in the different process than the one handling the request, the redirect response is rendered. This is really handy because you don't need to care where things are running. On the other hand, the price is that the applications using gateway need to support the post-through-redirect.

---------
Api calls
---------

By default the FEAT gateway of the master process listens on the port 5500. You can navigate there with your browser to see the autogenerated interface. Remember that you have to configure your browser first to provide the client SSL certificate. In development the certificate you need to provide is the one from *conf/dummy.p12* file. For production you should generate your own certificates, refer to `other documentation <https://github.com/f3at/feat/blob/master/doc/how-to-create-dev-pki.rst>`_ for explanation.

All HTTP api calls should have *Content-Type* and *Accept* headers set to *application/json*. The post body is a json dictionary with the keys matching parameter names.

Example curl command doing a request: ::

   curl --key dummy_private_key.pem --cert dummy_public_cert.pem
    --cacert gateway_ca.pem --insecure
    -H"Content-Type: application/json" -H"Accept: application/json"
     https://localhost:5500/aps/dns/servers

Note that *--insecure* option will not be needed if generate proper certificates with the subject name matching the hostname. Than, of course, you should use this host as the request target.

The following sections describe the api calls which are most likely for normal usage. Feat gateway is fanatically REST, meaning every single attribute has its own URL. Listing all of them in the next section would make it look more complicated that it really is. Instead at any time you can play with curl to discover the api. Adding *?format=verbose* to the url will make the current resource to explain himself in detail. Below you can see the example verbose response of */apps/dns/servers* resource. ::


    {
      "actions": {
	"post": {
	  "category": "command",
	  "label": "Start new server",
	  "href": "https://mkowalski.lan:5500/apps/dns/servers?format=verbose",
	  "params": {
	    "retry": {
	      "info": {
		"default": 300,
		"type": "integer"
	      },
	      "required": false,
	      "desc": "Interval before failed refresh should be retried"
	    },
	    "suffix": {
	      "info": {
		"type": "string"
	      },
	      "required": true
	    },
	    "expire": {
	      "info": {
		"default": 300,
		"type": "integer"
	      },
	      "required": false,
	      "desc": "Upper limit on time interval before expiry"
	    },
	    "refresh": {
	      "info": {
		"default": 300,
		"type": "integer"
	      },
	      "required": false,
	      "desc": "Number of seconds the zone should be refreshed"
	    },
	    "minimum": {
	      "info": {
		"default": 300,
		"type": "integer"
	      },
	      "required": false,
	      "desc": "Minimum TTL"
	    },
	    "slaves": {
	      "info": {
		"type": "string"
	      },
	      "required": false,
	      "desc": "Slaves to push zone updates. Format: 'ip:port, ip:port'"
	    },
	    "ns": {
	      "info": {
		"type": "string"
	      },
	      "required": false,
	      "desc": "The nameservers name"
	    }
	  },
	  "result": {
	    "type": "model"
	  },
	  "method": "POST"
	}
      },
      "desc": "List of servers running.",
      "name": "servers",
      "identity": "apps.dns.servers",
      "label": "Dns servers"
    }



Managing dns servers.
---------------------

* GET */apps/dns/servers*. List of running dns servers. The list includes information about the hosts the agents runs on and ports they listen.

* POST */apps/dns/servers*. Configure a new dns server. The server will handle a single dns zone. Fields of the JSON body:

 - *suffix*: The suffix of the zone. Only this field is mandatory.

 - *slaves*: List of slave servers to notify. Format 'ip1:port, ip2:port'. If port is ommited the default value of 53 is assumed.

 - *ns*: The nameservers name,

 - *refresh*: Number of seconds the zone should be refreshed,

 - *retry*: Interval before failed refresh should be retried,

 - *expire*: Upper limit on time interval before expiry,

 - *minimum*: Minimum TTL,


* DELETE */apps/dns/servers/<agent_id>*. Shutdown the agent with given ID.

Managing dns entries.
---------------------

* GET */apps/dns/entries/<suffix>*. Get the list of names registered in the zone.

* GET */apps/dns/entries/<suffix>/<name>*. Get the list of entries for the name.

* POST */apps/dns/entries/<suffix>*. Create a DNS entry. Fields of the JSON body:

 - *prefix*: Prefix of the entry.

 - *type*: Entry type. Can be 'record_A' or 'record_CNAME'.

 - *entry*: IP adress in case of record_A. In case of record_CNAME the name to alias.


* DELETE */apps/dns/entries/<suffix>/<name>/<entry>*. Remove dns entry or alias.


The actual example
==================

In this section I will demonstrate step by step how to run FEAT in development mode to see that it all works. We start from scratch only with named server configured as explained in the one of the previous sections. First lets get the latest checkout of FEAT: ::

  > git clone git@github.com:f3at/feat.git

Now lets open the other console and start CouchDB server. The version I'm using is 1.0.1. We will start it with the development script, which will create a fresh instance listing on the default port. This would collide on the listening port with the default system CouchDB so lets shut it down. ::

  > sudo /etc/inid.d/couchdb stop
  > tools/start_couch.sh

Now lets start yet another console. First load the *env* script. It sets PATH and PYTHONPATH to use uninstalled version of FEAT from the checkout. ::

  > ./env bash

We are ready to push the initial documents to database. ::

  > feat-dbload

Once this is done we can just start FEAT. It's done with the development script. It's just a wrapper around the *feat* command, adding some default options. ::

  > tools/start_feat.sh -c -d 3 -- --host-ports-ranges dns:5000:5010
                                   --host-category address:fixed

From now on FEAT is running. We can do some requests to the gateway. To keep it DRY lets create a helper script which I will name *request*. It will just call curl passing the common params. In my case it looks like this: ::

  #!/bin/sh
  curl --key conf/dummy_private_key.pem --cert conf/dummy_public_cert.pem
     --cacert conf/gateway_ca.pem -k -H"Content-Type: application/json"
     -H"Accept: application/json" https://localhost:5500"$@"


We are ready to request starting the dns server. In my case it looks like this. ::

  > ./request /apps/dns/servers
   -d'{"suffix":"service.flt.fluendo.lan","slaves": "192.168.64.11"}"

  {
    "message": "Server spawned",
    "href": "https://mkowalski.lan:5500/apps/dns/servers/eb250d6440e64c11fc4b679ec2011974",
    "type": "created"
  }

The *192.168.64.11* is the IP of the host I have my named server running. Lets take a look whats under the URL returned by the request. ::

   ./request /apps/dns/servers/eb250d6440e64c11fc4b679ec2019985
   {
     "ip": "172.17.5.52",
     "port": 5000,
     "slaves": "192.168.64.11:53",
     "suffix": "service.flt.fluendo.lan"
   }

We are ready to create an entry. I do this like this: ::

    > ./request /apps/dns/entries/service.flt.fluendo.lan -d
     '{"prefix": "spam", "entry": "1.2.3.4", "type": "record_A"}"

    {
      "message": "Entry created",
      "href": "https://mkowalski..lan:5500/apps/dns/entries/service.flt.fluendo.lan",
      "type": "created"
    }

This created an dns mapping pointing the address *spam.service.flt.fluendo.lan* to ip address *1.2.3.4*. Now lets do some DNS queries to see that it works. First query the local server. ::

    dig spam.service.flt.fluendo.lan @172.17.5.52 -p 5000

    ; <<>> DiG 9.7.0-P1 <<>> spam.service.flt.fluendo.lan @172.17.5.52 -p     5000
    ;; global options: +cmd
    ;; Got answer:
    ;; ->>HEADER<<- opcode: QUERY, status: NOERROR, id: 29122
    ;; flags: qr aa rd ra; QUERY: 1, ANSWER: 1, AUTHORITY: 0, ADDITIONAL:     0

    ;; QUESTION SECTION:
    ;spam.service.flt.fluendo.lan.	IN	A

    ;; ANSWER SECTION:
    spam.service.flt.fluendo.lan. 300 IN	A	1.2.3.4

    ;; Query time: 0 msec
    ;; SERVER: 172.17.5.52#5000(172.17.5.52)
    ;; WHEN: Tue Jan 10 12:49:42 2012
    ;; MSG SIZE  rcvd: 62


Also lets check that the zone has been transferred to the named server. ::

    ; <<>> DiG 9.7.0-P1 <<>> spam.service.flt.fluendo.lan @192.168.64.11
    ;; global options: +cmd
    ;; Got answer:
    ;; ->>HEADER<<- opcode: QUERY, status: NOERROR, id: 45755
    ;; flags: qr aa rd ra; QUERY: 1, ANSWER: 1, AUTHORITY: 1, ADDITIONAL:     0

    ;; QUESTION SECTION:
    ;spam.service.flt.fluendo.lan.	IN	A

    ;; ANSWER SECTION:
    spam.service.flt.fluendo.lan. 300 IN	A	1.2.3.4

    ;; AUTHORITY SECTION:
    service.flt.fluendo.lan. 300	IN	NS	mkowalski.flumotion.fluendo.lan.

    ;; Query time: 0 msec
    ;; SERVER: 192.168.64.11#53(192.168.64.11)
    ;; WHEN: Tue Jan 10 12:51:15 2012
    ;; MSG SIZE  rcvd: 96

We can see here that the entry is there. Also there is the authority section pointing to the FEAT dns server. This is basically all. Just for the sake of complicity I will shot how to remove this entry now and shutdown the server. Deleting the entry: ::

    ./request /apps/dns/entries/service.flt.fluendo.lan/spam/1.2.3.4 -X     DELETE
    {
      "message": "Entry deleted",
      "href": "https://mkowalski.lan:5500/apps/dns/entries/service.flt.fluendo.lan",
      "type": "deleted"
    }

At this point you can do the same dig query to see there is no entry. Now lets shut down the server: ::

    ./request /apps/dns/servers/eb250d6440e64c11fc4b679ec2019985 -X DELETE
    {
      "message": "Agent terminated",
      "href":     "https://mkowalski.lan:5500/apps/dns/servers",
      "type": "deleted"
    }

And this is really all now. Enjoy playing with it. At any time you want to stop feat you do this like this. ::

  > tools/stop_feat.sh
