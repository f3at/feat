import re

_regexp = re.compile('\A(\w+)://((\w+)(:(\w+))?@)?([\w\./]+)(:(\d+))?\Z')


def parse(connstr):
    global _regexp
    match = _regexp.search(connstr)
    if not match:
        raise ValueError("'%s' is not a valid connection string" %
                         (connstr, ))
    resp = dict()
    resp['protocol'] = match.group(1)
    resp['user'] = match.group(3)
    resp['password'] = match.group(5)
    resp['host'] = match.group(6)
    resp['port'] = match.group(8) and int(match.group(8))
    return resp
