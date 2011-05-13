from feat.test import common

from feat.common import manhole, serialization
from feat.common.serialization import sexp
from feat.agents.base import testsuite


class TestClass(manhole.Manhole):

    @manhole.expose()
    @serialization.freeze_tag('tag_name')
    def method(self):
        pass

    @serialization.freeze_tag('tag_other_name')
    @manhole.expose()
    def method2(self):
        pass


class FreezeTest(testsuite.TestCase):

    def testFreezetTag(self):
        test = TestClass()
        s = sexp.Serializer()
        self.assertEqual('tag_name', s.freeze(test.method))
        self.assertEqual('tag_other_name', s.freeze(test.method2))
