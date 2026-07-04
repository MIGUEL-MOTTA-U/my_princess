import sys
from pathlib import Path

import mongomock
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from my_princess.db import Database  # noqa: E402


@pytest.fixture
def db():
    """Base Mongo en memoria (mongomock): sin servidor real en los tests."""
    database = Database(client=mongomock.MongoClient())
    yield database
    database.close()
