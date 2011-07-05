import operator

from feat.test import common
from feat.common import mro, defer, fiber


class MroTestBase(mro.MroMixin):

    def __init__(self):
        self._calls = None
        self.reset()

    def reset(self):
        self._calls = list()

    def _call(self, cls, **kwargs):
        self._calls.append((cls, kwargs))
        return fiber.succeed(None)

    def get_keys(self):
        return map(operator.itemgetter(0), self._calls)

    def get_args(self, cls):
        for _cls, kwargs in self._calls:
            if _cls == cls:
                return kwargs
        raise KeyError('Missing calls for cls %r' % (cls, ))


class A(MroTestBase):

    def spam(self, param_A='default', default_none=None, default_true=True):
        assert default_none is None, default_none
        assert default_true is True, default_true
        return self._call(A, param_A=param_A)


class Blank(object):
    pass


class B(A, Blank):

    def spam(self, param_B):
        return self._call(B, param_B=param_B)


class C(B, A):

    def spam(self, default_sth='sth', param_C=None):
        assert default_sth == 'sth', default_sth
        return self._call(C, param_C=param_C)


class D(C):
    pass


class CallMroTest(common.TestCase):

    def setUp(self):
        self.instance = D()

    @defer.inlineCallbacks
    def testCallMro(self):
        f = self.instance.call_mro('spam', param_B='value')
        self.assertIsInstance(f, fiber.Fiber)
        yield f.start()
        self.assertEqual([A, B, C], self.instance.get_keys())
        self.assertEqual(dict(param_A='default'), self.instance.get_args(A))
        self.assertEqual(dict(param_B='value'), self.instance.get_args(B))
        self.assertEqual(dict(param_C=None), self.instance.get_args(C))

        self.instance.reset()
        f = self.instance.call_mro('spam', param_B='value', param_A='override')
        yield f.start()
        self.assertEqual([A, B, C], self.instance.get_keys())
        self.assertEqual(dict(param_A='override'), self.instance.get_args(A))
        self.assertEqual(dict(param_B='value'), self.instance.get_args(B))
        self.assertEqual(dict(param_C=None), self.instance.get_args(C))

        self.instance.reset()
        self.assertRaises(AttributeError, self.instance.call_mro, 'spam',
                          unknown_param='value')

        self.instance.reset()
        # now test missing param
        self.assertRaises(AttributeError, self.instance.call_mro, 'spam')
