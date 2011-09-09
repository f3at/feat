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
"""
Handle compatibility between spaces.

 - Converts charset names used in HTTP and XML from and to python compatible
   charset names used by codecs.

"""


_python2http = {"ascii": "us-ascii",
                "646": "us-ascii",
                "latin_1": "iso-8859-1",
                "iso8859_1": "iso-8859-1",
                "iso8859-1": "iso-8859-1",
                "8859": "iso-8859-1",
                "cp819": "iso-8859-1",
                "latin": "iso-8859-1",
                "latin1": "iso-8859-1",
                "L1": "iso-8859-1",
                "iso8859_2": "iso-8859-2",
                "iso8859-2": "iso-8859-2",
                "latin2": "iso-8859-2",
                "latin_2": "iso-8859-2",
                "L2": "iso-8859-2",
                "iso8859_2": "iso-8859-2",
                "iso8859-2": "iso-8859-2",
                "latin2": "iso-8859-2",
                "latin_2": "iso-8859-2",
                "L3": "iso-8859-3",
                "iso8859_3": "iso-8859-3",
                "iso8859-3": "iso-8859-3",
                "latin3": "iso-8859-3",
                "latin_3": "iso-8859-3",
                "L4": "iso-8859-4",
                "iso8859_4": "iso-8859-4",
                "iso8859-4": "iso-8859-4",
                "latin4": "iso-8859-4",
                "latin_4": "iso-8859-4",
                "iso8859_5": "iso-8859-5",
                "iso8859-5": "iso-8859-5",
                "cyrillic": "iso-8859-5",
                "iso8859_6": "iso-8859-6",
                "iso8859-6": "iso-8859-6",
                "arabic": "iso-8859-6",
                "iso8859_7": "iso-8859-7",
                "iso8859-7": "iso-8859-7",
                "greek": "iso-8859-7",
                "greek8": "iso-8859-7",
                "iso8859_8": "iso-8859-8",
                "iso8859-8": "iso-8859-8",
                "hebrew": "iso-8859-8",
                "L5": "iso-8859-9",
                "iso8859_9": "iso-8859-9",
                "iso8859-9": "iso-8859-9",
                "latin5": "iso-8859-9",
                "latin_5": "iso-8859-9",
                "L6": "iso-8859-10",
                "iso8859_10": "iso-8859-10",
                "iso8859-10": "iso-8859-10",
                "latin6": "iso-8859-10",
                "latin_6": "iso-8859-10",
                "iso8859_13": "iso-8859-13",
                "iso8859-13": "iso-8859-13",
                "L8": "iso-8859-14",
                "iso8859_14": "iso-8859-14",
                "iso8859-14": "iso-8859-14",
                "latin8": "iso-8859-14",
                "latin_8": "iso-8859-14",
                "iso8859_15": "iso-8859-15",
                "iso8859-15": "iso-8859-15",
                "iso2022_jp": "iso-2022-jp",
                "csiso2022jp": "iso-2022-jp",
                "iso2022jp": "iso-2022-jp",
                "iso2022_jp_1": "iso-2022-jp-1",
                "iso2022jp-1": "iso-2022-jp-1",
                "iso2022_jp_2": "iso-2022-jp-2",
                "iso2022jp-2": "iso-2022-jp-2",
                "iso2022_jp_3": "iso-2022-jp-3",
                "iso2022jp-3": "iso-2022-jp-3",
                "iso2022_kr": "iso-2022-kr",
                "csiso2022kr": "iso-2022-kr",
                "iso2022kr": "iso-2022-kr",
                "utf_7": "unicode-1-1-utf-7",
                "utf-7": "unicode-1-1-utf-7",
                "u7": "unicode-1-1-utf-7",
                "utf7": "unicode-1-1-utf-7",
                "utf_8": "unicode-1-1-utf-8",
                "utf-8": "unicode-1-1-utf-8",
                "u8": "unicode-1-1-utf-8",
                "utf8": "unicode-1-1-utf-8",
                "utf": "unicode-1-1-utf-8"}


_http2python = {"unicode-1-1-utf-7": "utf7",
                "unicode-1-1-utf-8": "utf8",
                "unicode-1-1": "utf"}


_python2xml = {"LATIN_1": "ISO-8859-1",
               "ISO8859_1": "ISO-8859-1",
               "ISO8859-1": "ISO-8859-1",
               "8859": "ISO-8859-1",
               "CP819": "ISO-8859-1",
               "LATIN": "ISO-8859-1",
               "LATIN1": "ISO-8859-1",
               "L1": "ISO-8859-1",
               "ISO8859_2": "ISO-8859-2",
               "ISO8859-2": "ISO-8859-2",
               "LATIN2": "ISO-8859-2",
               "LATIN_2": "ISO-8859-2",
               "L2": "ISO-8859-2",
               "ISO8859_2": "ISO-8859-2",
               "ISO8859-2": "ISO-8859-2",
               "LATIN2": "ISO-8859-2",
               "LATIN_2": "ISO-8859-2",
               "L3": "ISO-8859-3",
               "ISO8859_3": "ISO-8859-3",
               "ISO8859-3": "ISO-8859-3",
               "LATIN3": "ISO-8859-3",
               "LATIN_3": "ISO-8859-3",
               "L4": "ISO-8859-4",
               "ISO8859_4": "ISO-8859-4",
               "ISO8859-4": "ISO-8859-4",
               "LATIN4": "ISO-8859-4",
               "LATIN_4": "ISO-8859-4",
               "ISO8859_5": "ISO-8859-5",
               "ISO8859-5": "ISO-8859-5",
               "CYRILLIC": "ISO-8859-5",
               "ISO8859_6": "ISO-8859-6",
               "ISO8859-6": "ISO-8859-6",
               "ARABIC": "ISO-8859-6",
               "ISO8859_7": "ISO-8859-7",
               "ISO8859-7": "ISO-8859-7",
               "GREEK": "ISO-8859-7",
               "GREEK8": "ISO-8859-7",
               "ISO8859_8": "ISO-8859-8",
               "ISO8859-8": "ISO-8859-8",
               "HEBREW": "ISO-8859-8",
               "L5": "ISO-8859-9",
               "ISO8859_9": "ISO-8859-9",
               "ISO8859-9": "ISO-8859-9",
               "LATIN5": "ISO-8859-9",
               "LATIN_5": "ISO-8859-9",
               "L6": "ISO-8859-10",
               "ISO8859_10": "ISO-8859-10",
               "ISO8859-10": "ISO-8859-10",
               "LATIN6": "ISO-8859-10",
               "LATIN_6": "ISO-8859-10",
               "ISO8859_13": "ISO-8859-13",
               "ISO8859-13": "ISO-8859-13",
               "L8": "ISO-8859-14",
               "ISO8859_14": "ISO-8859-14",
               "ISO8859-14": "ISO-8859-14",
               "LATIN8": "ISO-8859-14",
               "LATIN_8": "ISO-8859-14",
               "ISO8859_15": "ISO-8859-15",
               "ISO8859-15": "ISO-8859-15",
               "ISO2022_JP": "ISO-2022-JP",
               "CSISO2022JP": "ISO-2022-JP",
               "ISO2022JP": "ISO-2022-JP",
               "ISO2022_JP_1": "ISO-2022-JP-1",
               "ISO2022JP-1": "ISO-2022-JP-1",
               "ISO2022_JP_2": "ISO-2022-JP-2",
               "ISO2022JP-2": "ISO-2022-JP-2",
               "ISO2022_JP_3": "ISO-2022-JP-3",
               "ISO2022JP-3": "ISO-2022-JP-3",
               "ISO2022_KR": "ISO-2022-KR",
               "CSISO2022KR": "ISO-2022-KR",
               "ISO2022KR": "ISO-2022-KR",
               "UTF_8": "UTF-8",
               "UTF-8": "UTF-8",
               "U8": "UTF-8",
               "UTF8": "UTF-8",
               "UTF": "UTF-8"}


def http2python(charset):
    """Convert a charset name from HTTP to python."""
    name = charset.lower()
    return _http2python.get(name, name)


def python2http(encoding):
    """Convert a charset name from python to HTTP."""
    name = encoding.lower()
    return _python2http.get(name, name)


def xml2python(encoding):
    """Convert a charset name from XML to python."""
    return encoding.lower()


def python2xml(encoding):
    """Convert a charset name from python to XML."""
    name = encoding.upper()
    return _python2xml.get(name, name)
