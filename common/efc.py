# -*- Mode: Python -*-
# vi:si:et:sw=4:sts=4:ts=4

from epyfilter import Start, Stop, Block

global starts, singles

starts = [
    Start('^=+$', [
        Stop('^$', [
            Block('In gtk'),
            Block('In gobject'),
            Block('In __builtin__'),
            Block('.*/twisted'),
        ])
    ]),
    Start('- TestResult', [
        Stop('TestCase.run\)$', [
            Block('from twisted.trial'),
        ])
    ]),
    Start('.*\/ihooks.py.*DeprecationWarning: The sre module', [
        Stop('.*return imp.load_source\(name, filename, file\)', [
            Block(None),
        ])
    ]),
    Start('.*epydoc\/uid.py:.*GtkDeprecationWarning', [
        Stop('.*obj not in self._module.value', [
            Block(None),
        ])
    ]),
    Start('.* - twisted\.', [
        Stop('.*\(base method=', [
            Block(None),
        ]),
        Stop('.*\(from twisted.*\)', [
            Block(None),
        ]),
    ]),
    Start('.* - pb.BrokerFactory', [
        Stop('.*\(from twisted.spread.flavors.Root\)', [
            Block(None),
        ])
    ]),
    Start('.* - TestResult', [
        Stop('.*\(from twisted.trial.unittest.TestCase.run\)', [
            Block(None),
        ])
    ]),
# +---------------------------------------------------------------------
# | File /usr/lib64/python2.7/site-packages/twisted/names/client.py,
# | line 261, in twisted.names.client.Resolver._query
# |   Warning: @param for unknown parameter "*args"
# |   
# ending in 3 spaces!
    Start('^\+\-*$', [
        Stop('^\|   $', [
            Block('^\| File .*/twisted/.*$'),
        ])
    ]),
]

singles = [
    "^Warning: <type 'exceptions\.",
    "^Warning: UID conflict detected: gobject",
    "^Warning: UID conflict detected: __builtin__",
    "^Warning: UID conflict detected: twisted",
    ".*- pb.getObjectAt \(from twisted.spread.flavors.Root\)",
    ".*- Deferred \(from twisted.trial.unittest.TestCase.run\)",
]
