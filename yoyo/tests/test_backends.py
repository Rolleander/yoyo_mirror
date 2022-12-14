from tempfile import NamedTemporaryFile
from threading import Thread
import time

from unittest.mock import Mock
from unittest.mock import call
from unittest.mock import patch
import pytest

from yoyo import backends
from yoyo import read_migrations
from yoyo import exceptions
from yoyo.backends.contrib.redshift import RedshiftBackend
from yoyo.connections import get_backend
from yoyo.tests import get_test_backends
from yoyo.tests import get_test_dburis
from yoyo.tests import migrations_dir


class TestTransactionHandling(object):
    def test_it_commits(self, backend):
        with backend.transaction():
            backend.execute("INSERT INTO yoyo_t values ('A')")

        with backend.transaction():
            rows = list(backend.execute("SELECT * FROM yoyo_t").fetchall())
            assert rows == [("A",)]

    def test_it_rolls_back(self, backend):
        with pytest.raises(backend.DatabaseError):
            with backend.transaction():
                backend.execute("INSERT INTO yoyo_t values ('A')")
                # Invalid SQL to produce an error
                backend.execute("INSERT INTO nonexistant values ('A')")

        with backend.transaction():
            rows = list(backend.execute("SELECT * FROM yoyo_t").fetchall())
            assert rows == []

    def test_it_nests_transactions(self, backend):
        if "redshift" in backend.uri.scheme:
            pytest.skip("Nested transactions not supported for Redshift")

        with backend.transaction():
            backend.execute("INSERT INTO yoyo_t values ('A')")

            with backend.transaction(rollback_on_exit=True):
                backend.execute("INSERT INTO yoyo_t values ('B')")

            with backend.transaction():
                backend.execute("INSERT INTO yoyo_t values ('C')")

        with backend.transaction():
            rows = list(backend.execute("SELECT * FROM yoyo_t").fetchall())
            assert rows == [("A",), ("C",)]

    def test_redshift_nested_transactions(self, backend):
        if "redshift" not in backend.uri.scheme:
            pytest.skip("Redshift only test")

        with backend.transaction():
            backend.execute("INSERT INTO yoyo_t values ('A')")

            with backend.transaction() as trans:
                backend.execute("INSERT INTO yoyo_t values ('B')")
                trans.rollback()

            with backend.transaction() as trans:
                backend.execute("INSERT INTO yoyo_t values ('C')")

        with backend.transaction():
            rows = list(backend.execute("SELECT * FROM yoyo_t").fetchall())
            assert rows == [("C",)]

    def test_backend_detects_transactional_ddl(self, backend):
        expected = {
            RedshiftBackend: True,
            backends.PostgresqlBackend: True,
            backends.SQLiteBackend: True,
            backends.MySQLBackend: False,
        }
        if backend.__class__ in expected:
            assert backend.has_transactional_ddl is expected[backend.__class__]

    def test_non_transactional_ddl_behaviour(self, backend):
        """
        DDL queries in MySQL commit the current transaction,
        but it still seems to respect a subsequent rollback.

        We don't rely on this behaviour, but it's weird and worth having
        a test to document how it works and flag up in future should a new
        backend do things differently
        """
        if backend.has_transactional_ddl:
            return

        with backend.transaction(rollback_on_exit=True):
            backend.execute("CREATE TABLE yoyo_a (id INT)")  # implicit commit
            backend.execute("INSERT INTO yoyo_a VALUES (1)")
            backend.execute("CREATE TABLE yoyo_b (id INT)")  # implicit commit
            backend.execute("INSERT INTO yoyo_b VALUES (1)")

        count_a = backend.execute("SELECT COUNT(1) FROM yoyo_a").fetchall()[0][0]
        assert count_a == 1

        count_b = backend.execute("SELECT COUNT(1) FROM yoyo_b").fetchall()[0][0]
        assert count_b == 0

    def test_statements_requiring_no_transaction(self):
        """
        PostgreSQL will error if certain statements (eg CREATE DATABASE)
        are run within a transaction block.

        As far as I know this behavior is PostgreSQL specific. We can't run
        this test in sqlite or oracle as they do not support CREATE DATABASE.
        """
        with migrations_dir(
            a="""
            __transactional__ = False
            step('CREATE DATABASE yoyo_test_tmp',
                'DROP DATABASE yoyo_test_tmp',
                )
        """
        ) as tmpdir:
            for backend in get_test_backends(exclude={"sqlite", "oracle"}):
                migrations = read_migrations(tmpdir)
                backend.apply_migrations(migrations)
                backend.rollback_migrations(migrations)

    def test_disabling_transactions_in_sqlite(self):
        """
        Transactions cause sqlite databases to become locked, preventing
        other tools from accessing them:

        https://bitbucket.org/ollyc/yoyo/issues/43/run-step-outside-of-transaction
        """
        with migrations_dir(
            a="""
            __transactional__ = False
            def reopen_db(conn):
                import sqlite3
                for _, db, filename in conn.execute('PRAGMA database_list'):
                    if db == 'main':
                        reconn = sqlite3.connect(filename)
                        reconn.execute("CREATE TABLE yoyo_test_b (id int)")
                        break
                else:
                    raise AssertionError("sqlite main database not found")

            step('CREATE TABLE yoyo_test_a (id int)')
            step(reopen_db)
            step('CREATE TABLE yoyo_test_c (id int)')
        """
        ) as tmpdir, NamedTemporaryFile() as tmp:
            backend = get_backend("sqlite:///" + tmp.name)
            backend.apply_migrations(read_migrations(tmpdir))
            assert "yoyo_test_a" in backend.list_tables()
            assert "yoyo_test_b" in backend.list_tables()
            assert "yoyo_test_c" in backend.list_tables()


class TestConcurrency(object):

    # How long to lock for: long enough to allow a migration to be loaded and
    # started without unduly slowing down the test suite
    lock_duration = 0.5

    def get_lock_sleeper(self, dburi):
        """
        Return a function that acquires the backend lock, then sleeps
        """
        backend = get_backend(dburi)

        def lock_sleep():
            with backend.lock():
                time.sleep(self.lock_duration)

        return lock_sleep

    def skip_if_not_concurrency_safe(self, backend):
        if "sqlite" in backend.uri.scheme and backend.uri.database == ":memory:":
            pytest.skip(
                "Concurrency tests not supported for SQLite "
                "in-memory databases, which cannot be shared "
                "between threads"
            )
        if backend.driver.threadsafety < 1:
            pytest.skip("Concurrency tests not supported for non-threadsafe backends")

    def test_lock(self, dburi):
        """
        Test that :meth:`~yoyo.backends.DatabaseBackend.lock`
        acquires an exclusive lock
        """
        backend = get_backend(dburi)
        self.skip_if_not_concurrency_safe(backend)
        thread = Thread(target=self.get_lock_sleeper(dburi))
        t = time.time()
        thread.start()

        # Give the thread time to acquire the lock, but not enough
        # to complete
        time.sleep(self.lock_duration * 0.6)

        with backend.lock():
            delta = time.time() - t
            assert delta >= self.lock_duration

        thread.join()

    def test_lock_times_out(self, dburi):

        backend = get_backend(dburi)
        self.skip_if_not_concurrency_safe(backend)

        thread = Thread(target=self.get_lock_sleeper(dburi))
        thread.start()
        # Give the thread time to acquire the lock, but not enough
        # to complete
        time.sleep(self.lock_duration * 0.6)
        with pytest.raises(exceptions.LockTimeout):
            with backend.lock(timeout=0.001):
                assert False, "Execution should never reach this point"

        thread.join()


class TestInitConnection(object):
    class MockBackend(backends.DatabaseBackend):
        driver = Mock(DatabaseError=Exception, paramstyle="format")

        def list_tables(self):
            return []

        def connect(self, dburi):
            return Mock()

    def test_it_calls_init_connection(self):

        with patch("yoyo.internalmigrations.upgrade"), patch.object(
            self.MockBackend, "init_connection", Mock()
        ) as mock_init:

            backend = self.MockBackend("", "")
            connection = backend.connection
            assert mock_init.call_args == call(connection)

            mock_init.reset_mock()
            backend.rollback()
            assert mock_init.call_args_list == [call(connection)]

    def test_postgresql_backend_sets_search_path(self):
        class MockPGBackend(backends.PostgresqlBackend):
            driver = Mock(DatabaseError=Exception, paramstyle="format")
            schema = "foo"

            def connect(self, dburi):
                return Mock()

        with patch("yoyo.internalmigrations.upgrade"):
            backend = MockPGBackend("", "")
            backend.rollback()
            assert backend.connection.cursor().execute.call_args == call(
                "SET search_path TO foo"
            )

    def test_postgresql_connects_with_schema(self):
        dburi = next(iter(get_test_dburis(only={"postgresql"})), None)
        if dburi is None:
            pytest.skip("PostgreSQL backend not available")
            return
        backend = get_backend(dburi)
        with backend.transaction():
            backend.execute("CREATE SCHEMA foo")
        try:
            assert get_backend(dburi + "?schema=foo").execute(
                "SHOW search_path"
            ).fetchone() == ("foo",)
        finally:
            with backend.transaction():
                backend.execute("DROP SCHEMA foo CASCADE")

    def test_postgresql_list_table_uses_current_schema(self):
        dburi = next(iter(get_test_dburis(only={"postgresql"})), None)
        if dburi is None:
            pytest.skip("PostgreSQL backend not available")
        backend = get_backend(dburi)
        dbname = backend.uri.database
        with backend.transaction():
            backend.execute(
                "ALTER DATABASE {} SET SEARCH_PATH = custom_schema,public".format(
                    dbname
                )
            )
        try:
            with backend.transaction():
                backend.execute("CREATE SCHEMA custom_schema")
                backend.execute("CREATE TABLE custom_schema.foo (x int)")
            assert "foo" in get_backend(dburi).list_tables()

        finally:
            with backend.transaction():
                backend.execute("ALTER DATABASE {} RESET SEARCH_PATH".format(dbname))
                backend.execute("DROP SCHEMA custom_schema CASCADE")

    def test_postgresql_migrations_can_change_schema_search_path(self):
        """
        https://todo.sr.ht/~olly/yoyo/72
        """
        dburi = next(iter(get_test_dburis(only={"postgresql"})), None)
        if dburi is None:
            pytest.skip("PostgreSQL backend not available")
        backend = get_backend(dburi)
        with migrations_dir(
            **{"1.sql": "SELECT pg_catalog.set_config('search_path', '', false)"}
        ) as tmpdir:
            migrations = read_migrations(tmpdir)
            backend.apply_migrations(migrations)
            applied = backend.execute("SELECT migration_id FROM _yoyo_log").fetchall()
            assert applied == [("1",)]
