from feat.test import common


try:
    import psycopg2
    import psycopg2.extensions
except ImportError:
    psycopg2 = None



DB_NAME = "feat_test"
DB_HOST = "localhost"
DB_USER = "feat_test"
DB_PASSWORD = "feat_test"

def getSkipForPsycopg2():
    if not psycopg2:
        return "psycopg2 not installed"
    try:
        psycopg2.extensions.POLL_OK
    except AttributeError:
        return ("psycopg2 does not have async support. "
                "You need at least version 2.2.0 of psycopg2 "
                "to use txpostgres.")
    try:
        psycopg2.connect(user=DB_USER, password=DB_PASSWORD,
                         host=DB_HOST, database=DB_NAME).close()
    except psycopg2.Error, e:
        return ("cannot connect to test database %r "
                "using host %r, user %r, password: %r, %s" %
                (DB_NAME, DB_HOST, DB_USER, DB_PASSWORD, e))
    return None


_skip = getSkipForPsycopg2()


class TestPostgressWriter(common.TestCase):

    skip = _skip

    def setUp(self):
        pass

    def testItWorks(self):
        pass
