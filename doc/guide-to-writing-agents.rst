=======================
Guide to writing agents
=======================

This document explains the constrains and gains introduced by the feat framework
upon the agents code. The reason for most of the design decisions made is to
meat the difficult requirement of code replayability. Replayability of the code
means, that during the runtime we keep enough information to later understand
why certain steps have been taken, this is called a journal.


Concept of the hamster ball
===========================

The structure of the feat framework is essentially divided into two parts:

- Agency, the layer responsible for transport layers,

- Agent, the code taking all the decisions, performing the real job.


The Agency code is not meant to be replayable. Obviously it is impossible task,
as this layer is responsible for all the IO operations. On the agent side
however, all the decisions can be tracked, replayed and analyzed. This obvious
gain comes for the price of course. The constrains set up to make replayability
work can be summarized in the following points (which are explained further in this section):

1. Each object has a state, which he guards against the changes done outside of	his context.

2. All the decisions done by the replayable instance are done in methods, which call will be recorded in the journal.

3. The replayable objects can be created only on replayable context.

4. Changes done in the state outside of these methods are **considered a bug**.

5. Running the asynchronous task (running something which return a Deferred and binding a callback) inside the replayable code is **considered a bug**.

6. Object leaving inside the hamster ball cannot be changed from outside.

7. All the objects which are being put into the state needs to be serializable (implement f.c.s.ISerializable or subclass f.c.s.Serializable).

8. Also they need to implement custom \_\_eq\_\_ (and \_\_ne\_\_) methods.



MutableState object
-------------------

The simplest replayable one can think of would look somewhat like this: ::

    from feat.agents.base import replay

    class ReplayableObject(replay.Replayable):

    	  def __init__(self, recorder, *args, **kwargs):
	      replay.Replayable.__init__(self, recorder, *args, **kwargs)

	  def init_state(self, state, recorder, *args, **kwargs):
	      state.variable = 'whatever'

A lot of moving points here, lets explain a little:

- The constructor parameter *recorder* needs to implement the *journal.IRecorderNode* and *journal.IJournalKeeper* interfaces. You probably should pass the *f.a.agency.AgencyAgent* instance here.

- The init\_state() method is initializing the state of the object after it has been created. It **is not** in replayable context. It will run in the replay mode only if the object is created from the replayable function body. If the object is loaded from the snapshot the method will not run. This method also doesn't perform any asynchronous job, it should not return anything.


Modifying the state
-------------------

So how do we access the state once it has been created? This is as simple as providing the correct decorator to the function. Lets take a look at the code:::

   class MutatingReplayable(ReplayableObject):

   	 def init_state(self, state, recorder, first_value):
	     state.value = first_value

   	 @replay.mutable
	 def add_one(self, state):
	     state.value += 1

	 @replay.immutable
	 def get_value(self, state):
	     return state.value

	 @replay.journaled
	 def create_some_object(self, state):
	     SomeOtherReplayableObject()


In the example above the following points are worth to mention:

- The init\_state() function takes extra parameter which it puts into it's state.

- The add\_one() method is marked as a replay.mutable, which has the following effects:

  - The method will receive the state of the object as a parameter. It still should be used as instance.add\_one() with no parameters. The state is added by the decorator.

  - Running it will create a journal entry. This journal entry will include the serialized parameters, the *side effects* run and the created *fiber* (to be explained further).

- The get\_value() method is marked as replay.immutable. This means that:

  - The journal entry will not be created for the calls of this one. It will be run in the replay mode only if triggered from inside of the methods decorated with *mutable* or *journaled*.

  - The whole gain from using this decorator is that we get the access to the instances state. It is especially useful for running methods on the objects, references to which we keep in our state.

- The method create\_some\_object() doesn't change the internal state of the object, however it still needs to run in the replay mode. The reason for this is that it creates an object which would live inside the hamster ball. We want this method to be replayed when recovering the journal. Note that in version 0.1 of journaled decorator is just the other name for the mutable. However the difference should be made to take advantage of it in future.


What not to do
--------------

Below the few examples of code **which should never be written**.::

      import uuid

      from twisted.web import client


      class VeryBadClass(ReplayableObject):

      	    def get_to_the_state_in_illegal_way(self):
	    	state = self._get_state()
		state.variable = 5

	    @replay.mutable
	    def use_instance_variable_to_take_decisions(self, state):
	    	'''
		The instance variable will not be set correctly during the
		replay. This means that the state modified basing on they
		values will probably be wrong.
		'''
	    	if self.weather == 'sunny':
		    state.variable = 5
                else:
 		    state.variable = 10

 	    @replay.mutable
	    def use_asynchronous_operations_to_modify_the_state(self, state):
	    	'''
		We don't want this to happen during the replay mode. The
		communication needs to be mocked out. The correct way of doing
		this is creating a Fiber and making the store_result mutable
		instance method.
		'''

		def store_result(result):
		    state.result = result

		d = client.getPage(url)
		d.addCallback(store_result)

	    @replay.immutable
	    def modify_the_state_from_immutable(self, state):
	    	'''
		For Gods sake! Use the freaking mutable for this!
		'''
		state.variable = 5

	    @replay.mutable
	    def pseudorandom_or_nondeterministic_call(self, state):
	    	'''
		The way to get around this limitation is to use the function
		inside the side effect function. This way it will not be run
		again during the replay, its result will be stored and reused.
		'''
	    	state.name = str(uuid.uuid1())


Getting around the constrains.
------------------------------

So far the limitations presented make the usefulness of the framework questionable. Using twisted without the Deferred would be quite devastating. Also it is quite obvious that in the end we need to call methods which result is not deterministic (they use io operations for example). The solution to the problem is quite complex, but can be summarized with the following rule: if something is not neat enough to live inside the hamster ball, we need to delegate it outside. Framework supplies us with two powerful tool for performing this task: the *fibers* and the *side effects*.


Fibers
``````
Fibers are the serializable representation of the asynchronous chain of events. They a lot in common with the Deferreds. The key difference is that the Fiber can be created, triggered, but it will not start performing the job before the execution frame gets out of the hamster ball. When it happens the Fiber is run and transformed into the Deferred. From the outside-of-hamsterball point of view the code leaving inside always returns the Deferred.

Here is the correct implementation of function getting the webpage and storing it to the state from the previous sections::

     from twisted.web import client

     from feat.common import fiber
     from feat.agents.base import replay

     class BetterClass(VeryBadClass):

     	   @replay.mutable
	   def use_asynchronous_operations_to_modify_the_state(self, state,
							       url):
               state.url = url

	       f = fiber.Fiber()
	       f.add_callback(client.getPage)
	       f.add_callback(self.store_result)
	       f.add_errback(self.handle_error)
	       return f.succeed(url)

	   @replay.mutable
	   def store_result(self, state, result):
	       state.result = result


So what happens here is quite complex. The entry point is the use_asynchronous_operations_to_modify_the_state() method being run. It stores the url inside the state and constructs the fiber. The client.getPage is not run from this method though. Although the fiber is trigger with the succeed(url) call, it is not started yet. It will get started when the execution frame leaves the hamster ball, by the code inside the mutable() decorator. When this happens the client.getPage will be run, and the .store_result method will be added as its callback.

When it gets executed the result is stored in the state and the journal entry is created. So the actual html body of the document will be stored inside a journal in the argument of the call of the BetterClass.store_result method.

In the replay mode on the other hand, the fiber would not be started. So the client.getPage method would never get called. What would happen instead is that the fiber constructed would be compared to the one taken from the journal entry. If some parameters/methods are different we would get the ReplayError exception.

Two points from this discussion are worth being summarized:

- When we need to use asynchronous call and modify the state based on its result we need to split this into two methods: the one before yielding and the one after.

- **The Fiber is never run in the replay mode**. All the methods bounded there are mocked out. Nice, hugh?


Side effects
````````````

Side effects are also not being executed in the replay mode. What happens instead is that their parameters and return values are stored in the journal, and the driver makes assertions that the same call is generated during the replay.

Below is the rewrite of problematic function from the previous sections. ::

     class BetterClass(VeryBadClass):

	    @replay.mutable
	    def pseudorandom_or_nondeterministic_call(self, state):
	    	'''
	    	state.name = self._generate_name()

	    @replay.side_effect
	    def _generate_name(self):
	    	return str(uuid.uuid1())

What happens now is the method \_generate\_name() runs only in production mode. When it does the result of this is stored in the journal entry of the method which called it. During the replay of this entry the value is recovered.

Question arises: can also keep on using the *side_effect* function outside of the *mutable* context? Of course you can. If you do, it will just behave as a normal method.

Other point worth mentioning here is that the code of the side effect is considered as leaving outside of the hamster ball. This means that it cannot change the state of the objects passed to it as a reference. The following example explains the difference.::

      from feat.common import serialization

      @serialization.register
      class Rectangle(serialization.Serializable):

      	    def __init__(self, a, b):
	    	self.a = a
		self.b = b


      class BadReplayableAgain(ReplayableObject):

      	   @replay.mutable
      	   def do_some_stuff_with_rectangle(self, state, rectangle):
	       state.rect = rectangle
	       self._grow_rectangle_and_send_it(rectangle)

	   @replay.side_effect
	   def _grow_rectangle_and_send_it(self, rectangle):
	       # Following line fixes the problem:
	       # rectangle = copy.deepcopy(rectangle)

	       rectangle.a *= 2
	       rectangle.b *= 2
	       send(rectangle)

The problem with the code above is that the side effect function gains the access to the state of the replayable object by the reference to the object which is stored inside. If this code would be left like this the state of the object produced by the replay would have a smaller rectangle inside that the one from the production code. The point is: **complex objects need to be copied before they are mutated**.

There is one more important point worth making: *side_effect* methods needs to be **synchronous**. They cannot return Deferred as it is impossible to compare two of them. If you need to call something asynchronous use should construct a *Fiber* and add it as a callback.


Creating objects capable of being part of the state
---------------------------------------------------

As mentioned before, there are two constrains set upon the objects which are going to be put into the objects state. First of all they need to be serializable. The easiest way of creating a serializable class is subclassing f.c.serialization.Serializable and registering it to the (un)serializer with the class decorator. Take a look at the Rectangle class implementation from the previous section.

The default behavior of the Serializable is to put into snapshot all the public attributes. The attributes starting with the underscore will be ignored. If you need different behavior you need to overload the *snapshot()* and *recover()* methods. Take a look at feat.agents.base.document.Document implementation for a good example how to do that.

The second constraint put here is the necessity of implementing custom \_\_eq\_\_() method. The reason for this is the default implementation would return True only for the same instance of the complex object. During the validation of replayability of the code we need to use two instances and than compare them.


Creating a new agent
======================

First of all, the code layout. The agents leave in feat.agents module. For example Host Agent code will go to feat.agents.host module.

Secondly, the minimum code we write is:

- The agent class, subclass of the feat.agents.base.agent.

- The agents descriptor - representation of its persistent state stored in the database.

With this in mind the minimal implementation would look somewhat like this: ::

     from feat.agents.base import agent, descriptor, document


     @agent.register('insulter_agent')
     class InsulterAgent(agent.BaseAgent):

          @replay.mutable
     	  def initiate(self, state):
	        agent.BaseAgent.initiate(self)
		# do here whatever you need now


     @descriptor.register('insulter_agent')
     class Descriptor(descriptor.Descriptor):
          pass

And this is it! Now if you create a Descriptor instance, save it to the database and pass it as a parameter to Agency.start\_agent you will have your agent running. Although it doesn't do anything yet.


Developing it further
---------------------

First of all, BaseAgent is a subclass of f.agent.b.replay.Replayable which means that everything said in the first section of this document is valid for the agent. But of course there is more agent-specific stuff.

The best way to learn it quickly is to take a look at the existing agents implementation. Inside the agents state there is *medium* reference, which implements the IAgencyAgent interface. This interface lets you alter the database, start requests and contracts, express interests and all the other things which agents like to do.

Below I will only sketch the most basic usage scenario.


Updating descriptor
```````````````````

Lets say our agent whats to store some piece of persistent information. The persistence here means, that the information will outlive the agent, in case he will get restarted. This is responsibility of the initiate() method.

First lets make our Descriptor a little bit more interesting: ::

     @descriptor.register('insulter_agent')
     class Descriptor(descriptor.Descriptor):

	  document.field('parent', None)
	  document.field('temperature', 20)

Above 2 fields have been declared with some default values. Now it is possible to create the instance passing the dictionary of custom values to the constructor (ie. Descriptor(temperature=1)).

Second lets write a method changing something. This is perform with the *update_descriptor* decorator. ::

      class InsulterAgent(...):

	    ...
	    @agent.update_descriptor
	    def change_temperature(self, state, descriptor, temperature):
	    	descriptor.temperature = temperature

And this is it. The method can be called as instance.change_temperature(100). After it finishes the new version of the descriptor will be saved to the database. In case of the conflict during saving (which indicated duplicate of the agents instance running) the proper action will be taken (although this is not yet implemented in v0.1 tag).


Defining and using the resources
````````````````````````````````

Most of the agents needs to handle some kind of resources. The resource is a quantifiable amount which can be (pre)allocated. Take a look at the implementation (feat.agents.base.resource). Below is the example of how it may be used: ::

     class InsulterAgent(...):

     	   @replay.mutable
     	   def initiate(self, state):
	       state.resources.define('cpu', 100)
	       state.resources.define('memory', 4000)
	       self.make_some_allocations()

	   @replay.mutable
	   def make_some_allocations(self, state):
	       # this will return a feat.agents.base.resource.Allocation
	       # instance which will not expire
	       state.resources.allocate(cpu=20)

	       # this one will expire after timeout if not confirmed
	       allocation = state.resources.preallocate(memory=30,cpu=20)
	       state.resources.confirm(allocation.id)
	       # or state.resources.release(allocation.id)

	       # this will return None as we don't have enough resource
	       state.resources.preallocate(cpu=200)

	       # be carefull! this will throw NotEnoughResources
   	       state.resources.allocate(cpu=200)

Important thing to point out here is that confirmed allocations are stored in the descriptor in order to survive the agents restart. For this reason .allocate(), .confirm() and .release() methods return a Fiber instance which you should chain or returned. The reason for this is that they modify descriptor which requires performing the HTTP request. Note that this is not done in the example above in order to keep it simple.


Defining and using partners
```````````````````````````

No man is an island. Same applies to agents. If your task at hand can be performed by a single agent it means you are wasting time reading this guide.

Framework comes with a handy utility class (feat.agents.base.partners.Partners) which is here to help you manage relations between agents. Lets take a look at the following code: ::


    class JohnPartner(partners.BasePartner):
        pass


    class DogPartner(partners.BasePartner):
        pass


    class CatPartner(partners.BasePartner):
        pass


    class DefaultPartner(partners.BasePartner):
        pass


    class Partners(partners.Partners):

        default_handler = DefaultPartner
        partners.has_one("john", "john_agent", JohnPartner)
        partners.has_many("dogs", insulter_agent", DogPartner, "dog")
        partners.has_many("cats", "insulter_agent", CatPartner, "cat")


    class InsulterAgent(...):

    	partners_class = Partners

	def initiate(...):
	    BaseAgent.initiate(self)
	    .......
	    .......
	    return self.initiate_partners()

	@replay.mutable
	def do_sth_with_partners(self, state):
	    # this is how we query
	    john = self.partners.john

	    f = fiber.Fiber()
	    # make an allocation (lets say we can partner
	    # limited number of dogs)
	    f.add_callback(fiber.drop_result, self.allocate_resource,
	                   dog=1)
	    # establish partnership
	    f.add_callback(self.bind_with_a_dog)
	    return f.succeed()

	@replay.journaled
	def bind_with_a_dog(self, state, allocation):
	    dog_recp = recipient.Agent('dog_that_we_no_about',
				       'some shard')
	    f = fiber.Fiber()
 	    # this will create a correct Partner
	    # instances in both agents
	    f.add_callback(self.establish_partnership, allocation.id,
	                   partner_role="dog", our_role="cat")
	    return f.succeed(dog_recp)


A lot of code! Lets explain in points:

- JohnPartner, DogPartner, CatPartner and DefaultPartner are subclassing the partners.BasePartner class. This class contains two important piece of information: the resource allocation's id reflecting our side of partnership and the IRecipient address of the partner. It comes with 3 methods which you might or might not overload. All of them receive an agent instance as a parameter:

  - *.initiate(agent)* is called when the partnership is being established. Here you should perform our part of the job triggered by the agent. So, if we are speaking about HostAgent code and initiate() method of ShardPartner we should change a shard. MonitorPartner (of any agent) should initiate the heartbeat signals, JournalPartner would setup sending the journal pages and so on, so on.

  - *.on_goodbye(agent)* is called when the partner on the other side sends us a goodbye message. Possibly someone terminated him.. how sad. But life goes on! Usually this method should be responsible for running a  contract to find a substitute. Superclass implementation just removes the partner from the descriptor, so don't forget to call it when your custom code is finished.

  - *.on_shutdown(agent)* is called when our agent has been requested to terminate. Superclass implementation sends the goodbye message to the partner. Overload it if you need to do anything more here.

- Partners subclasses the partners.Partners and uses annotations to define what type of agents we subclass and what Partner classes should be used to represent them. You should always define a Partner class for an agent you are writing. Then it is bind together by *partner\_class* class attribute in agent class definition.

  - *default\_handler* attribute defines what factory should be used if we end up in a couple with the stranger (for which we don't have matching  *has\_one*\/*has\_many* definition)

  - *has\_one(name, identifier, factory, role=None)* tells us that we might want are relating ourselves to one agent using *identifier* (this is a string you put to *@agent.register()* decorator). For this agent partner class *factory* should be used. Optionally you might also pass a *role*. This is useful if you need to form couples with the same type of agent taking different roles. This happens for example for the Shard Agent which relates to other Shard Agents as the parent or a child. This statement defines the *name* attribute on the Partners class which will return the interesting partner (of None if we don't have one).

  - *has\_many(name, identifier, factory, role=None)* if very much alike, but represent the one-to-many relation. The only difference is that now the *name* attribute on the Partners class will return a list() (which might be empty of course).


Taking parts in contracts and requests
``````````````````````````````````````

This section is just a sketch, for more information please take a look at the UML diagrams (in doc directory) and the existing implementations. The basics go as follow, we have two types of protocols:

- Requests - a very simple protocol, just sends a requests to get the response or fail with the timeout. Two sides of communication takes part, and to implement them you need to subclass certain classes:

  - Requester - subclass the feat.agents.base.requester.BaseRequester class

  - Replier - subclass the feat.agents.base.replier.BaseReplier class

- Contracts - much more complicated. Consists of multiple phases which point is to decide who is going to perform the task contracted. In the process we have following sides:

  - One manager, which subclass the feat.agents.base.manager.BaseManager class and initiates the process.

  - Multiple contractors, subclassing the feat.agents.base.contractor.BaseContractor class which express interest in the type of contracts and listen for the announcements coming in.

All the agent-side classes forming the communication framework also subclass the f.a.b.replay.Replayable class, have the guarded internal state and leave inside the hamster ball.
