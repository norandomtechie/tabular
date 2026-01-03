#! /usr/bin/env python3
import re
import os
import sys
import json
import redis
from functools import reduce

NAME_RGX = r'^[a-zA-Z0-9_\- ]{3,25}$'

# path to private directory for logs and db files
try:
    private = '/web/groups/' + os.environ['USER'] + '/private/scheduler/'
except:
    private = os.environ['CONTEXT_DOCUMENT_ROOT'].replace('public_html', 'private') + 'scheduler/'

rds = redis.Redis(unix_socket_path=open(private + 'redis_socket').read().strip())

sys.path.append(private + 'lib')

from scheduler import *
from wsgidefs import *

def authentication(app):
    def middleware(env, sr):
        if env.get('REMOTE_USER', '').replace('@purdue.edu', '') != '':
            return app(env, sr)
        else:
            return ret_401(sr, "Unauthorized")
    return middleware

# API:
"""
GET /scheduler/?id=<id> - get scheduler with id, check if user is in users, return 400 if not, return JSON of scheduler if so
POST /scheduler/?name=<name> - create a new scheduler, return 400 if user is not in users or data is not expected, return 200 if successful
    - data saved should be JSON of scheduler, with name, description, sections, users
    - return ID of scheduler
POST /scheduler/?id=<id> - updates properties of the scheduler JSON, return 400 if user is not in users or data is not expected, return 200 if successful
    - data should be ["timeslot1": (N, '=/+/-'), "timeslot2": (N, '=/+/-'), ...]
    - save under "users" under respective section under "sections"

- Redis key: scheduler:\<scheduler_id\> (UUID)
- scheduler:\<scheduler_id\> is a JSON key-value object containing:
    - name: string
    - description: string
    - sections: dict
        - section number: dict
            - day: string
            - time range: tuple[string, string]
            - prefs: list
                - user: dict key
                    - score: int
                    - span: char ('=', '+', '-')
    - limit (number of people per section): int
    - options: object
        - ac-sections: bool
    - users
        - visitable: list [string, ...]
        - editable: list [string, ...]
        - admin: list [string, ...]
    
"""

def validate_request(app):
    def middleware(env, sr):
        if env['QUERY_STRING'] == '':
            return ret_400(sr, "Invalid request")
        if env['REQUEST_METHOD'] == 'POST':
            try:
                length = int(env.get('CONTENT_LENGTH', 0))
            except:
                length = 0
        return app(env, sr)
    return middleware

def scheduler_api_get(app):
    def middleware(env, sr):
        if env['REQUEST_METHOD'] == 'GET':
            user = env.get('REMOTE_USER', '').replace('@purdue.edu', '')
            query = {k:v for k, v in [x.split('=') for x in env['QUERY_STRING'].split('&')]}
            if 'id' in query:
                try:
                    scheduler = from_json(json.loads(rds.get("scheduler:" + query['id']).decode('utf8')))
                except:
                    return ret_400(sr, "Invalid request")
                # only allow user if they are in visitable/editable/admin of scheduler.users
                # all_users = reduce(lambda x, y: x+y, [scheduler.users[k] for k in scheduler.users], [])
                # if user in all_users:
                scheduler_json = scheduler.to_json()
                # remove others prefs if user is not admin
                if user not in scheduler.users['admin']:
                    for section in scheduler_json['sections']:
                        if user in scheduler_json['sections'][section]['prefs']:
                            scheduler_json['sections'][section]['prefs'] = {user: scheduler_json['sections'][section]['prefs'][user]}
                        else:
                            scheduler_json['sections'][section]['prefs'] = {user: {'score': 0, 'span': '='}}
                # add availability
                scheduler_json['availability'] = scheduler.compute_availability()
                scheduler_json['is_admin'] = user in scheduler.users['admin']
                scheduler_json['is_editable'] = user in scheduler.users['editable']
                return ret_ok(sr, json.dumps(scheduler_json))
                # else:
                #     return ret_400(sr, "User not in users")
            else:
                return ret_400(sr, "Invalid request")
        else:
            return app(env, sr)
    return middleware
        
def scheduler_api_post(app):
    def middleware(env, sr):
        if env['REQUEST_METHOD'] == 'POST':
            user = env.get('REMOTE_USER', '').replace('@purdue.edu', '')
            body = json.loads(env['wsgi.input'].read(int(env.get('CONTENT_LENGTH', 0))))
            # sys.stderr.write('body: ' + str('addedit' in body) + '\n')
            if 'id' in body:
                # fetch from redis
                scheduler = from_json(json.loads(rds.get("scheduler:" + body['id']).decode('utf8')))
                all_users = reduce(lambda x, y: x+y, [scheduler.users[k] for k in scheduler.users], [])
                if user not in all_users:
                    return ret_400(sr, "User not in users")
                elif 'addedit' in body:
                    # expected format: {"admin": [user], "editable": [user], "visitable": [user]}
                    # combine with existing editable set
                    if user in scheduler.users['admin']:
                        body['addedit'] = body['addedit'].replace(" ", "").split(",")
                        scheduler.users['editable'] = list(set(scheduler.users['editable'] + body['addedit']))
                        rds.set("scheduler:" + body['id'], json.dumps(scheduler.to_json()))
                        return ret_ok(sr, "Updated users\n" + ','.join(scheduler.users['editable']))
                    else:
                        return ret_403(sr, "You are not admin")
                elif 'remedit' in body:
                    # expected format: {"remedit": [user1, user2, ...]}
                    if user in scheduler.users['admin']:
                        body['remedit'] = body['remedit'].replace(" ", "").split(",")
                        scheduler.users['editable'] = [u for u in scheduler.users['editable'] if u not in body['remedit']]
                        rds.set("scheduler:" + body['id'], json.dumps(scheduler.to_json()))
                        return ret_ok(sr, "Updated users\n" + ','.join(scheduler.users['editable']))
                    else:
                        return ret_403(sr, "You are not admin")
                elif 'timeslots' in body:
                    # expected format: {"sectionN2": ['N1', '=/+/-'], "sectionN2": ['N2', '=/+/-'], ...}
                    # can only update user's own prefs
                    if user not in scheduler.users['editable']:
                        return ret_403(sr, "You are not allowed to edit")
                    for s in body['timeslots']:
                        v = body['timeslots'][s]
                        section_num = s
                        prefnum = int(v[0]) if len(v[0]) == 1 else int(v[0][0])
                        prefspan = v[1] if len(v[1]) == 1 else v[1][0]
                        scheduler.sections[section_num]['prefs'][user] = {'score': prefnum, 'span': prefspan}
                    rds.set("scheduler:" + body['id'], json.dumps(scheduler.to_json()))
                    return ret_ok(sr, json.dumps(scheduler.compute_availability()))
                else:
                    return ret_400(sr, "Invalid request")
            elif 'name' in body and 'description' in body and 'sections' in body:
                # then we are creating a new scheduler
                users = {"admin": [user], "editable": [user], "visitable": [user]}
                if not re.match(NAME_RGX, body['name']):
                    return ret_400(sr, "Invalid name")
                scheduler = Scheduler(body['name'], body['description'], body['sections'], users)
                rds.set("scheduler:" + scheduler.id, json.dumps(scheduler.to_json()))
                return ret_ok(sr, scheduler.id)
        return app(env, sr)
    return middleware

def catch_all(env, sr):
    return ret_400(sr, "No idea what you're looking for")

MIDDLEWARES = [
    authentication, 
    validate_request,
    scheduler_api_get, 
    scheduler_api_post
]

application = reduce(lambda f, g: g(f), MIDDLEWARES, catch_all)
