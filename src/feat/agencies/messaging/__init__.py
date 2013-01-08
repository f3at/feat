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
# -*- Mode: Python -*-
# vi:si:et:sw=4:sts=4:ts=4

import os

from feat.common import log

from .messaging import *


env_set = os.environ.get("FEAT_DEBUG_MESSAGES", "NO").upper() \
          in ("YES", "1", "TRUE")


def debug_message(prefix, message, postfix=""):
    global env_set
    if not env_set:
        return
    mtype = type(message).__name__
    mid = getattr(message, "message_id", None)
    mrec = getattr(message, "recipient", None)
    mrec = mrec.key if mrec is not None else None
    mrep = getattr(message, "reply_to", None)
    mrep = mrep.key if mrep is not None else None
    log.debug("messages",
              "%s Type: %s; Id: %s; Recipient: %s; Reply-To: %s; %s",
              prefix, mtype, mid, mrec, mrep, postfix)
