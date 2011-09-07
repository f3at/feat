# F3AT - Flumotion Asynchronous Autonomous Agent Toolkit
# Copyright (C) 2010,2011 Flumotion Services, S.A.
# All rights reserved.

# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License along
# with this program; if not, write to the Free Software Foundation, Inc.,
# 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA.

# See "LICENSE.GPL" in the source distribution for more information.

# Headers in this file shall remain intact.
from feat.agents.migration import protocol
from feat.common import serialization, formatable
from feat.agents.base import view


###### METHODS CALLED BY MIGRATION AGENT ON EXPORT AGENT #######


### handshake ###


@serialization.register
class HandshakeResponse(protocol.BaseResponse):

    formatable.field('name', None)
    formatable.field('version', None)


@serialization.register
class Handshake(protocol.BaseCommand):

    response_factory = HandshakeResponse

    formatable.field('method', 'migration_handshake')


### get_shard_structure ###


@serialization.register
class GetShardStructureResponse(protocol.BaseResponse):

    # ShardStructure entries
    formatable.field('shards', list())


@view.register
@serialization.register
class ShardStructure(view.FormatableView):
    # NOTE FOR LATER: after versioned formatables are done this class should
    # inherit from sth like FormatableVersionedView
    name = "shard_structure"

    def map(doc):
        if doc['.type'] == 'shard_agent':
            hosts = list()
            for p in doc['partners']:
                if p['.type'] == 'shard->host':
                    hosts.append(p['recipient']['key'])
            yield doc['shard'], dict(agent_id=doc['_id'],
                                     shard=doc['shard'],
                                     hosts=hosts)
    view.field('agent_id', None)
    view.field('shard', None)
    view.field('hosts', list())


@serialization.register
class GetShardStructure(protocol.BaseCommand):

    response_factory = GetShardStructureResponse

    formatable.field('method', 'migration_get_shard_structure')


### prepare_migration ###


class _MigrationResponse(protocol.BaseResponse):

    formatable.field('ident', None)
    formatable.field('completable', False)
    formatable.field('completed', False)


@serialization.register
class PrepareMigrationResponse(_MigrationResponse):
    pass


@serialization.register
class PrepareMigration(protocol.BaseCommand):

    response_factory = PrepareMigrationResponse
    formatable.field('method', 'migration_prepare_migration')
    formatable.field('recipient', None)
    formatable.field('migration_agent', None)
    formatable.field('host_cmd', None)


### join migrations ###


@serialization.register
class JoinMigrationsResponse(_MigrationResponse):
    pass


@serialization.register
class JoinMigrations(protocol.BaseCommand):

    response_factory = JoinMigrationsResponse
    formatable.field('method', 'migration_join_migrations')
    formatable.field('migration_ids', list())
    formatable.field('migration_agent', None)
    formatable.field('host_cmd', None)



### show_migration ##


@serialization.register
class ShowMigrationResponse(protocol.BaseResponse):

    formatable.field('text', '')


@serialization.register
class ShowMigration(protocol.BaseCommand):

    response_factory = ShowMigrationResponse
    formatable.field('method', 'migration_show_migration')
    formatable.field('migration_id', None)


### apply_next_step ###


@serialization.register
class ApplyNextMigrationStepResponse(_MigrationResponse):
    pass


@serialization.register
class ApplyNextMigrationStep(protocol.BaseCommand):

    response_factory = ApplyNextMigrationStepResponse
    formatable.field('method', 'migration_apply_next_step')
    formatable.field('migration_id', None)


### apply_migration_step ###


@serialization.register
class ApplyMigrationStepResponse(_MigrationResponse):
    pass


@serialization.register
class ApplyMigrationStep(protocol.BaseCommand):

    response_factory = ApplyMigrationStepResponse
    formatable.field('method', 'migration_apply_migration_step')
    formatable.field('migration_id', None)
    formatable.field('index', None)


### forget_migration ###


@serialization.register
class ForgetMigrationResponse(protocol.BaseResponse):
    pass


@serialization.register
class ForgetMigration(protocol.BaseCommand):

    response_factory = ForgetMigrationResponse
    formatable.field('method', 'migration_forget_migration')
    formatable.field('migration_id', None)


###### METHODS CALLED BY EXPORT AGENT ON MIGRATION AGENT #######

### handle_import ###


@serialization.register
class HandleImportResponse(protocol.BaseResponse):
    pass


@serialization.register
class HandleImport(protocol.BaseCommand):

    response_factory = HandleImportResponse
    formatable.field('method', 'migration_handle_import')
    formatable.field('agent_type', None)
    formatable.field('blackbox', None)
