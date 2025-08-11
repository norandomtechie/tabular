import os
import redis

# path to private directory for logs and db files
try:
    private = '/web/groups/' + os.environ['USER'] + '/private/queup/'
except:
    private = os.environ['CONTEXT_DOCUMENT_ROOT'].replace('public_html', 'private') + 'queup/'

# redis client object
rds = redis.Redis(unix_socket_path=open(private + 'redis_socket').read().strip())

class Scheduler:
    def __init__(self, name, description="", sections={}, users={}, limit=100, options={}):
        self.name = name
        self.description = description
        # modify sections to be a dictionary of dictionaries
        # e.g. from ["day", "time range"] to {"day": "day", "timeRange": "time range", "prefs": {}}
        # unless it is already in the correct format
        if not all([isinstance(v, dict) for v in sections.values()]):
            self.sections = {str(k): {"day": v[0], "timeRange": v[1], "prefs": {}} for k, v in sections.items()}
        else:
            self.sections = sections
        self.limit = limit
        self.options = options
        self.users = users
        # generate a unique id for the scheduler from the name, using only lowercase alphanumeric characters
        self.id = "".join([c.replace(' ', '-') for c in name.lower() if (c.isalnum() or (c == ' '))])
    def to_json(self):
        return {
            "name": self.name,
            "description": self.description,
            "sections": self.sections,
            "users": self.users,
            "limit": self.limit,
            "options": self.options
        }
    def compute_availability(self):
        # for all sections, compute the availability of each user's preferences (score, span)
        # availability = ((score * (span == '=' ? 1 : 0.5)) for all users) / number of users
        # user prefs are stored in self.sections[section_num]['prefs'][user]
        availability = {}
        for section, data in self.sections.items():
            availability[section] = {}
            score = 0
            if "prefs" in data:
                for user, prefs in data["prefs"].items():
                    score += prefs["score"] * (1 if prefs["span"] == "=" else 0.5)
            availability[section] = score
        # return {"section": availability, ...}
        return availability

def from_json(j):
    return Scheduler(j["name"], j["description"], j["sections"], j["users"], 
        j["limit"] if "limit" in j else 100, 
        j["options"] if "limit" in j else {}
    )