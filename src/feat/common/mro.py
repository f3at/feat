import inspect

from feat.common import fiber


class MroMixin(object):

    def call_mro(self, method_name, **keywords):
        cls = type(self)
        klasses = list(cls.mro())
        klasses.reverse()

        f = fiber.succeed()

        consumed_keys = set()
        for klass in klasses:
            method = klass.__dict__.get(method_name, None)
            if not method:
                continue
            if hasattr(method, 'original_func'):
                function = method.original_func
            else:
                function = method

            argspec = inspect.getargspec(function)
            defaults = argspec.defaults and list(argspec.defaults) or list()
            kwargs = dict()
            for arg in argspec.args:
                if arg in ['self', 'state']:
                    continue
                if arg in keywords:
                    consumed_keys.add(arg)
                    kwargs[arg] = keywords[arg]
                elif len(defaults) > 0:
                    kwargs[arg] = defaults.pop(0)
                else:
                    msg = ("Missing value for keyword argument %s "
                           "of the method %r" % (arg, method))
                    raise AttributeError(msg)

            f.add_callback(fiber.drop_param, method, self, **kwargs)

        diff = set(keywords.keys()) - consumed_keys
        if diff:
            msg = ('Unconsumed arguments %r while calling mro method %s' %
                   (diff, method_name))
            raise AttributeError(msg)

        return f
