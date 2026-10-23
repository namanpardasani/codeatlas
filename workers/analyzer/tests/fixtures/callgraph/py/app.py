import pkg.db
from pkg import Account
from pkg.models import User, Admin
from pkg import util
import json


def make(name):
    u = User(name)
    u.rename("b")
    acct = Account(name)
    pkg.db.connect()
    util.helper()
    Admin.create(name)
    json.dumps({})
    getattr(u, "display")()

    def inner():
        return make("x")
    return inner()


def process(items):
    for it in items:
        it.save()
    print(len(items))


class Service:
    def __init__(self, store: "User"):
        self.store = store
        self.cache = User("cache")

    def run(self, other: User):
        self.cache.display()
        other.rename("z")
        self.missing()


make("a")
