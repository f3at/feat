from feat.agents.base import poster, replay
from feat.agencies import recipient


class ConfigurationPoster(poster.BasePoster):

    protocol_id = 'nagios-config'

    @replay.immutable
    def pack_payload(self, state, config_body):
        origin = state.agent.get_own_address()
        return origin, config_body


def create_poster(agent):
    recp = recipient.Broadcast(ConfigurationPoster.protocol_id, 'lobby')
    return agent.initiate_protocol(ConfigurationPoster, recp)
