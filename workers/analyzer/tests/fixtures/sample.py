"""module doc"""
import os
import os.path as p
from a.b import c, d as e
from . import sibling
from ..pkg import thing
from m import *

__all__ = ["public_fn", "Klass"]


@decorator
async def public_fn(a, b: int = 1, *args, **kwargs):
    """Docstring."""
    def inner(): pass


def _private(x): return x


class Klass(Base):
    def method(self, y): pass

    @staticmethod
    def static(): pass


handler = lambda event: event
