import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app  # noqa: E402
import db as dbmod  # noqa: E402


@pytest.fixture
def app(tmp_path):
    application = create_app(db_path=str(tmp_path / "test.db"))
    application.config["TESTING"] = True
    return application


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def conn(app, tmp_path):
    connection = dbmod.connect(str(tmp_path / "test.db"))
    yield connection
    connection.close()
