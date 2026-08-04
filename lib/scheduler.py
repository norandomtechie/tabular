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
        self.limit = limit
        self.options = options
        # modify sections to be a dictionary of dictionaries
        # e.g. from ["day", "time range"] to {"day": "day", "timeRange": "time range", "prefs": {}}
        # or, in direct-assignment mode, ["day", "time range", capacity] to
        # {"day": "day", "timeRange": "time range", "prefs": {}, "signups": {}, "capacity": capacity}
        # unless it is already in the correct format
        if not all([isinstance(v, dict) for v in sections.values()]):
            direct = self.options.get('mode') == 'direct'
            default_capacity = self.options.get('defaultCapacity', 5)
            new_sections = {}
            for k, v in sections.items():
                entry = {"day": v[0], "timeRange": v[1], "prefs": {}}
                if direct:
                    entry["signups"] = {}
                    entry["capacity"] = int(v[2]) if len(v) > 2 and v[2] else int(default_capacity)
                new_sections[str(k)] = entry
            self.sections = new_sections
        else:
            self.sections = sections
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
            score = 0
            for user, prefs in data.get("prefs", {}).items():
                score += prefs["score"] * (1 if prefs["span"] == "=" else 0.5)
            availability[section] = score
        # return {"section": availability, ...}
        return availability
    def section_occupancy(self, section):
        # direct-assignment mode: how full is each half of this section?
        # a full-time ('=') signup occupies both halves; a half signup ('+'/'-') occupies only its half.
        # a section is only closed to new full-time signups once BOTH halves are at capacity;
        # if only one half is full, the other half can still accept half-time signups
        # (this is what lets an extra TA join to "cover the uncovered half").
        data = self.sections[section]
        capacity = data.get("capacity", self.limit)
        signups = data.get("signups", {})
        first_occupied = sum(1 for v in signups.values() if v["span"] in ("=", "+"))
        second_occupied = sum(1 for v in signups.values() if v["span"] in ("=", "-"))
        return {
            "capacity": capacity,
            "firstOccupied": first_occupied,
            "secondOccupied": second_occupied,
            "firstOpen": first_occupied < capacity,
            "secondOpen": second_occupied < capacity,
            "fullOpen": first_occupied < capacity and second_occupied < capacity,
        }
    def compute_occupancy(self):
        return {section: self.section_occupancy(section) for section in self.sections}
    def user_section_count(self, user):
        return sum(1 for data in self.sections.values() if user in data.get("signups", {}))

def from_json(j):
    return Scheduler(j["name"], j["description"], j["sections"], j["users"],
        j["limit"] if "limit" in j else 100,
        j["options"] if "options" in j else {}
    )
