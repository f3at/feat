#!/usr/bin/env python

import os
from setuptools import setup, find_packages
from distutils.command import clean


feat_args = dict(name='feat',
                 version='0.1.1',
                 description='Flumotion Asynchronous Autonomous Agent Toolkit',
                 author='Flumotion Developers',
                 author_email='coreteam@flumotion.com',
                 platforms=['any'],
                 package_dir={'': 'src'},
                 packages=find_packages(where='src', exclude=['flt*']),
                 scripts=['src/feat/bin/bootstrap.py', 'src/feat/bin/host.py',
                          'src/feat/bin/standalone.py'],
                )

flt_args = dict(name='flt',
                version='0.1.1',
                description='Flumotion Live Transcoding',
                author='Flumotion Developers',
                author_email='coreteam@flumotion.com',
                platforms=['any'],
                package_dir={'': 'src'},
                packages=find_packages(where='src', exclude=['feat*']),
               )


def clean_build(dist):
    c = clean.clean(dist)
    c.initialize_options()
    c.finalize_options()
    c.all = True
    c.run()

if os.path.isdir('src/feat'):
    feat_dist = setup(**feat_args)

if os.path.isdir('src/flt'):
    if os.path.isdir('src/feat'):
        clean_build(feat_dist)
        os.mkdir('build')
    setup(**flt_args)
