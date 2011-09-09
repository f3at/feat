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
from zope.interface import implements, classProvides

from feat.agents.base import replay, labour
from feat.common import serialization

from feat.agents.alert.interface import *


@serialization.register
class MailLabour(labour.BaseLabour):

    classProvides(IEmailSenderLabourFactory)
    implements(IAlertSenderLabour)

    @replay.side_effect
    def send(self, config, msg, severity):
        """Nothing"""


@serialization.register
class NagiosLabour(labour.BaseLabour):

    classProvides(INagiosSenderLabourFactory)
    implements(IAlertSenderLabour)

    @replay.side_effect
    def send(self, config, msg, severity):
        """Nothing"""
