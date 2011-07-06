from twisted.python import components

from feat.agents.base import (descriptor, message, replay,
                              contractor, recipient, )
from feat.common import fiber, formatable, enum, serialization, manhole
from feat.agents.common import rpc


class Migratability(enum.Enum):
    '''
    not_migratable - agent cannot be moved and will live as long as cluster
                     leaves (DNS, Hapi)
    locally        - agent can move but in the same shard (structural agents)
    globally       - agent can move anywhere (alert agent)
    exportable     - agent can be exported to the other cluster
    shutdown       - just shutdown the agent (worker, manager, fsp, etc)
    host           - special strategy for host agent
    '''
    not_migratable, locally, globally, exportable, shutdown, host = range(6)


class CheckInContractor(contractor.NestingContractor):

    protocol_id = 'check_in'

    @replay.entry_point
    def announced(self, state, announcement):
        state.migration_id = announcement.payload.ident
        keep_sender = (announcement.level == 0)
        # If we are on lvl 0 it means that we are host agent and it was
        # export agent who sended this announcement. If he is running on
        # the same host, we want to include him.
        f = fiber.succeed()
        f.add_callback(fiber.drop_param, state.agent.get_migration_partners)
        f.add_callback(self.fetch_nested_bids, announcement,
                       keep_sender=keep_sender)
        f.add_callback(self._checkin_yourself)
        return f

    @replay.mutable
    def _checkin_yourself(self, state, bids):
        f = state.agent.checkin_for_migration()
        f.add_callback(self._generate_bid, bids)
        return f

    @replay.mutable
    def _generate_bid(self, state, own_entry, bids):
        entries = list()
        for bid in bids:
            entries += bid.payload
        entries += [own_entry]
        state.agent.set_migrating(state.migration_id)

        bid = message.Bid()
        bid.payload = entries
        state.medium.bid(bid)

    @replay.mutable
    def _cancel_migration(self, state, *_):
        state.agent.unregister_from_migration(state.migration_id)

    expired = _cancel_migration
    cancelled = _cancel_migration
    aborted = _cancel_migration

    def rejected(self, rejection):
        self._cancel_migration()
        self.terminate_nested_manager()

    @replay.entry_point
    def granted(self, state, grant):
        self.grant_nested_bids(grant)
        f = self.wait_for_nested_complete()
        f.add_callback(fiber.drop_param, self._finalize)
        return f

    @replay.journaled
    def _finalize(self, state):
        state.medium.finalize(message.FinalReport())


class AgentMigrationBase(object):

    migratability = None

    @replay.mutable
    def initiate(self, state):
        # known migrations we are under
        state.migrations = list()
        state.medium.register_interest(CheckInContractor)

    ### TO BE OVERLOADED ###

    def set_migration_dependencies(self, entry):
        '''
        Overload this method with code like this.
        entry.add_dependency(agent_id1)
        entry.add_dependency(agent_id2)
        Agent with IDs specified will have to be migrated before this agent.
        '''
        pass

    def get_migration_partners(self):
        '''
        Overload this method to specify the list of recipients of the agents
        which should be set into migrating phase with us and notified.
        Note that this is different kind of information from the dependencies.
        Dependencies are one way for of relation which express the order in
        which migration of agents will be handled. The migration partners
        relation is symetrical and is used to discover logical connections
        between agents.
        '''
        return list()

    ### END OF METHODS TO BE OVERLOADED ###

    @replay.immutable
    def is_migrating(self, state):
        return len(state.migrations) > 0

    @replay.mutable
    def checkin_for_migration(self, state):
        if not isinstance(self.migratability, Migratability):
            raise AttributeError('Agent class should override migratability '
                                 'attribute!')
        recp = self.get_own_address()
        entry = CheckinEntry(agent_id=recp.key, shard=recp.shard,
                             migratability=self.migratability,
                             agent_type=self.descriptor_type,
                             hostname=state.medium.get_hostname())
        f = fiber.succeed()
        f.add_callback(fiber.drop_param, self.set_migration_dependencies,
                       entry)
        f.add_callback(fiber.override_result, entry)
        return f

    @rpc.publish
    @replay.mutable
    def set_migrating(self, state, migration_id):
        if migration_id in state.migrations:
            raise RuntimeError("Requested to checkin for migration with id "
                               "%r, for which we are already checked in.",
                               migration_id)
        state.migrations.append(migration_id)

    @rpc.publish
    @replay.journaled
    def get_migration_blackbox(self, state):
        if hasattr(self, 'get_migration_state'):
            return self.get_migration_state()

    @rpc.publish
    @manhole.expose()
    @replay.mutable
    def unregister_from_migration(self, state, migration_id):
        if migration_id not in state.migrations:
            raise KeyError("unregister_from_migration() called with "
                           "migration_id: %r, but the migrations we know "
                           "at this point are: %r." %
                           (migration_id, state.migrations, ))
        state.migrations.remove(migration_id)


@descriptor.register('export_agent')
class Descriptor(descriptor.Descriptor):

    # agent_id -> [PendingNotification]
    formatable.field('pending_notifications', dict())


@serialization.register
class CheckinEntry(formatable.Formatable):

    type_name = 'checkin_entry'

    formatable.field('agent_id', None)
    formatable.field('shard', None)
    # f.a.b.export.Migratability
    formatable.field('migratability', None)
    # list of ids of the agents which need to be handled before
    formatable.field('dependencies', list())
    # information usefull only for debuging and inspection purpouse
    formatable.field('agent_type', None)
    formatable.field('hostname', None)

    def get_dependant_entries(self, data):
        '''
        Returns the list of entry object reflecing our dependencies.
        If entry is not found the original key is returned.
        '''

        def key_func(x):
            if isinstance(x, CheckinEntry):
                return (x.agent_type, x.agent_id, )
            else:
                return x

        entries = map(lambda x: data.get(x, x), self.dependencies)
        return sorted(filter(None, entries), key=key_func)

    def add_dependency(self, agent_id):
        if isinstance(agent_id, CheckinEntry):
            agent_id = agent_id.agent_id
        if agent_id in self.dependencies:
            self.log("Agent id %r already in dependencies of the entry %r",
                     agent_id, self)
            return
        self.dependencies.append(agent_id)

    def remove_dependency(self, agent_id):
        if isinstance(agent_id, CheckinEntry):
            agent_id = agent_id.agent_id
        if agent_id not in self.dependencies:
            self.log("Agent id %r was not in dependencies of the entry %r, "
                     "so it cannot be removed", agent_id, self)
        self.dependencies.remove(agent_id)


class RecipientFromCheckinEntry(recipient.Recipient):

    type_name = 'recipient'

    def __init__(self, entry):
        recipient.Recipient.__init__(self, entry.agent_id, entry.shard)


components.registerAdapter(RecipientFromCheckinEntry, CheckinEntry,
                           recipient.IRecipient)
components.registerAdapter(RecipientFromCheckinEntry, CheckinEntry,
                           recipient.IRecipients)
