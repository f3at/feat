Merging notes
-------------

1. There is a significant change in how we handle scaling time in tests. Unfortunately this means going through all the simulation you have and updating them. On bright side of this, is that when you're done your test should run in about 30% of time it takes now.

The feat.common.delay has been removed. Instead use feat.common.time. In places where you had: ::

   class SomeTest(common.SimulationTest):

	 def testCaseWithScaledTime(self):
	    delay.time_scale = 0.8

now use: ::

   class SomeTest(common.SimulationTest):

   	 @common.attr(timescale=0.05)
	 def testCaseWithScaledTime(self):

Note that you can decorate the whole class if all the testcase use the same scale. It is important that time is scaled in by the decorator, because it makes it set early enough not to run into some strange problems.

Also in case you override *.setUp()* please make sure to call the super classes one.

And the most important thing: almost all feat simulation cases work now with scale **0.05**. The reason we were using higher values was inconsistency on expiration times we had. You should aim to using the same. If you tests don't pass try using higher values. The highest value we use is **0.2**, and it is used in simulations of a really big cluster with lots of agents. If you discover you need to use values like this (or even higher), this most likely indicated problems of some other nature.
