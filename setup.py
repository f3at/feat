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
#!/usr/bin/env python
from setuptools import setup, find_packages

setup(name='feat',
      version='0.10',
      description='Flumotion Asynchronous Autonomous Agent Toolkit',
      author='Flumotion Developers',
      author_email='coreteam@flumotion.com',
      platforms=['any'],
      package_dir={'': 'src',
                   'paisley': 'src/feat/extern/paisley/paisley/'},
      packages=(find_packages(where='src') +
                find_packages('src/feat/extern/paisley')),
      scripts=['bin/feat',
               'bin/feat-couchpy',
               'bin/feat-dbload',
               'bin/feat-locate',
               'bin/feat-service'],

      package_data={'': ['src/feat/agencies/net/amqp0-8.xml']},
      include_package_data=True,
)
