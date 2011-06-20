from feat.process.rabbitmq import Process, RabbitMQCtl


@agent.register('shard_agent')
class RabbitMQAgent(agent.BaseAgent):

    @replay.entry_point
    def initiate(self, state):
        agent.BaseAgent.initiate(self)
        return self.initiate_partners()



    # read nodes from DB?
    # start rabbitmq on current machine
    # join cluster???
    # reconnections?
