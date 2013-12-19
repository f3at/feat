import pprint

from feat.gateway.application import featmodels

from feat.database import driver
from feat.models import model, value, getter, response, action, call, setter

from feat.models.interface import IModel, ActionCategories


@featmodels.register_adapter(driver.Database, IModel)
@featmodels.register_model
class Database(model.Model):

    model.identity('feat.database.Database')
    model.child('cache', source=getter.source_attr('_cache'))
    model.attribute('host', value.String(), getter.source_attr('host'))
    model.attribute('port', value.Integer(), getter.source_attr('port'))
    model.attribute('connected', value.Boolean(),
                    call.source_call('is_connected'))

    model.meta("html-order", "host, port, connected, cache")


@featmodels.register_adapter(driver.Cache, IModel)
@featmodels.register_model
class Cache(model.Model):

    model.identity('feat.database.Cache')
    model.attribute('size', value.Integer(),
                    desc="Sum of sizes of cached fragments",
                    getter=call.source_call('get_size'))
    model.attribute('average_size', value.Integer(),
                    desc="Average size of cache calculated during the "
                         "cleanup call",
                    getter=call.model_call('get_average_size'))
    model.attribute('average_cleanup_time', value.Integer(),
                    desc="Average size of cache calculated during the "
                         "cleanup call",
                    getter=call.model_call('get_average_cleanup_time'))
    model.attribute('desired_size', value.Integer(),
                    desc="Desired size of cache.",
                    getter=getter.source_attr('desired_size'),
                    setter=setter.source_attr('desired_size'))
    model.attribute('operation', value.Integer(),
                    desc=("Internal counter of operations used to "
                          "determine when to call cleanup()"),
                    getter=getter.source_attr('_operation'))
    model.collection('entries',
                     child_names=call.source_call('keys'),
                     child_source=getter.source_get('get'),
                     child_model='feat.database.CacheEntry',
                     meta=[('html-render', 'array, 4')],
                     model_meta=[('html-render',
                                  'array-columns, id, tag, state, '
                                  'cached_at, last_accessed_at, '
                                  'num_accessed, size')])

    def get_average_size(self):
        return self.source.average_size.get_value()

    def get_average_cleanup_time(self):
        return self.source.average_cleanup_time.get_value()

    model.action('cleanup', action.MetaAction.new(
        'cleanup',
        ActionCategories.command,
        effects=[call.source_call('cleanup'),
                 response.done('Done')],
        result_info=value.Response()),
                 label="Trigger normal cleanup")

    model.delete('del',
                 call.source_call('clear'),
                 response.done('Done'),
                 desc="Clean all the entries from the cache",
                 label="Clean all")


@featmodels.register_adapter(driver.CacheEntry, IModel)
@featmodels.register_model
class CacheEntry(model.Model):

    model.identity('feat.database.CacheEntry')
    model.attribute('tag', value.String(), getter=getter.source_attr('tag'))
    model.attribute('state', value.Enum(driver.EntryState),
                    getter=getter.source_attr('state'))
    model.attribute('cached_at', value.Integer(),
                    getter=getter.source_attr('cached_at'))
    model.attribute('last_accessed_at', value.Integer(),
                    getter=getter.source_attr('last_accessed_at'))
    model.attribute('num_accessed', value.Integer(),
                    getter=getter.source_attr('num_accessed'))
    model.attribute('size', value.Integer(),
                    getter=getter.source_attr('size'))
    model.attribute('etag', value.String(),
                    getter=getter.source_attr('etag'))
    model.item_meta("tag", "html-link", "owner")

    model.action('response', action.MetaAction.new(
        'response',
        ActionCategories.retrieve,
        effects=[getter.source_attr('_parsed'),
                 call.model_perform('pprint')],
        result_info=value.String()),
                 label="Get cached response")

    def pprint(self, value):
        return pprint.pformat(value)

    model.meta("html-order", "tag, state, cached_at, last_accessed_at, "
               "num_accessed, size, etag, response")
