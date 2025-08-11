#! /usr/bin/env python3
import re
import os
import sys
import json
import redis
from functools import reduce

# path to private directory for logs and db files
try:
    private = '/web/groups/' + os.environ['USER'] + '/private/scheduler/'
except:
    private = os.environ['CONTEXT_DOCUMENT_ROOT'].replace('public_html', 'private') + 'scheduler/'

rds = redis.Redis(unix_socket_path=open(private + 'redis_socket').read().strip())

