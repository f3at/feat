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
            for arg, default_index in zip(argspec.args,
                                          range(-len(argspec.args), 0)):
                if arg in ['self', 'state']:
                    continue
                if arg in keywords:
                    consumed_keys.add(arg)
                    kwargs[arg] = keywords[arg]
                else:
                    try:
                        kwargs[arg] = defaults[default_index]
                    except IndexError:
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
