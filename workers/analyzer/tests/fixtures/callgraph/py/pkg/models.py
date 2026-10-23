from .util import slugify as slug
from . import db


class Base:
    def save(self):
        db.write(self)

    def validate(self):
        return True


class User(Base):
    def __init__(self, name):
        self.name = slug(name)
        self.validate()

    def rename(self, n):
        self.name = n
        self.save()
        return self.display()

    def display(self):
        return self.name.strip()


class Admin(User):
    def __init__(self, name):
        super().__init__(name)

    @classmethod
    def create(cls, name):
        return cls.build(name)

    @staticmethod
    def build(name):
        return Admin(name)
