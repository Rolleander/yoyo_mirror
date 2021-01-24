import pytest

from yoyo import backends
from yoyo.connections import get_backend
from yoyo.tests import dburi_sqlite3
from yoyo.tests import get_test_backends
from yoyo.tests import get_test_dburis


def _backend(dburi):
    """
    Return a backend configured in ``test_databases.ini``
    """
    backend = get_backend(dburi)
    with backend.transaction():
        if backend.__class__ is backends.MySQLBackend:
            backend.execute(
                "CREATE TABLE yoyo_t "
                "(id CHAR(1) primary key) "
                "ENGINE=InnoDB"
            )
        else:
            backend.execute("CREATE TABLE yoyo_t " "(id CHAR(1) primary key)")
    try:
        yield backend
    finally:
        backend.rollback()
        drop_yoyo_tables(backend)


@pytest.fixture(params=get_test_dburis())
def backend(request):
    """
    Return all backends configured in ``test_databases.ini``
    """
    yield from _backend(request.param)


@pytest.fixture()
def backend_sqlite3(request):
    yield from _backend(dburi_sqlite3)


@pytest.fixture(params=get_test_dburis())
def dburi(request):
    try:
        yield request.param
    finally:
        drop_yoyo_tables(get_backend(request.param))


def drop_yoyo_tables(backend):
    for table in backend.list_tables():
        if table.startswith("yoyo") or table.startswith("_yoyo"):
            with backend.transaction():
                backend.execute("DROP TABLE {}".format(table))


def pytest_configure(config):
    for backend in get_test_backends():
        drop_yoyo_tables(backend)
