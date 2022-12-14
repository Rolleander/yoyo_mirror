# Copyright 2015 Oliver Cope
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from datetime import datetime
from datetime import timedelta
from unittest.mock import Mock, patch
import io
import os

import pytest

from yoyo.connections import get_backend
from yoyo import read_migrations
from yoyo import exceptions
from yoyo import ancestors, descendants

from yoyo.tests import migrations_dir
from yoyo.tests import tempdir
from yoyo.migrations import MigrationList
from yoyo.scripts import newmigration


def test_transaction_is_not_committed_on_error(backend_sqlite3):
    with migrations_dir(
        'step("CREATE TABLE yoyo_test (id INT)")',
        """
        step("INSERT INTO yoyo_test VALUES (1)")
        step("INSERT INTO yoyo_test VALUES ('x', 'y')")
        """,
    ) as tmpdir:
        migrations = read_migrations(tmpdir)
        with pytest.raises(backend_sqlite3.DatabaseError):
            backend_sqlite3.apply_migrations(migrations)
        backend_sqlite3.rollback()
        cursor = backend_sqlite3.cursor()
        cursor.execute("SELECT count(1) FROM yoyo_test")
        assert cursor.fetchone() == (0,)


def test_rollbacks_happen_in_reverse(backend_sqlite3):
    with migrations_dir(
        'step("CREATE TABLE yoyo_test (id INT)")',
        """
        step(
            "INSERT INTO yoyo_test VALUES (1)", "DELETE FROM yoyo_test WHERE id=1"
        )
        step(
            "UPDATE yoyo_test SET id=2 WHERE id=1",
            "UPDATE yoyo_test SET id=1 WHERE id=2"
        )
        """,
    ) as tmpdir:
        migrations = read_migrations(tmpdir)
        backend_sqlite3.apply_migrations(migrations)
        cursor = backend_sqlite3.cursor()
        cursor.execute("SELECT * FROM yoyo_test")
        assert cursor.fetchall() == [(2,)]
        backend_sqlite3.rollback_migrations(migrations)
        cursor.execute("SELECT * FROM yoyo_test")
        assert cursor.fetchall() == []


def test_execution_continues_with_ignore_errors(backend_sqlite3):
    with migrations_dir(
        """
        step("CREATE TABLE yoyo_test (id INT)")
        step("INSERT INTO yoyo_test VALUES (1)")
        step("INSERT INTO yoyo_test VALUES ('a', 'b')", ignore_errors='all')
        step("INSERT INTO yoyo_test VALUES (2)")
        """
    ) as tmpdir:
        migrations = read_migrations(tmpdir)
        backend_sqlite3.apply_migrations(migrations)
        cursor = backend_sqlite3.cursor()
        cursor.execute("SELECT * FROM yoyo_test")
        assert cursor.fetchall() == [(1,), (2,)]


def test_execution_continues_with_ignore_errors_in_transaction(backend_sqlite3):
    with migrations_dir(
        """
        from yoyo import step, group
        step("CREATE TABLE yoyo_test (id INT)")
        group(
            step("INSERT INTO yoyo_test VALUES (1)"),
            step("INSERT INTO yoyo_test VALUES ('a', 'b')"),
            ignore_errors='all'
        )
        step("INSERT INTO yoyo_test VALUES (2)")
        """
    ) as tmpdir:
        migrations = read_migrations(tmpdir)
        backend_sqlite3.apply_migrations(migrations)
        cursor = backend_sqlite3.cursor()
        cursor.execute("SELECT * FROM yoyo_test")
        assert cursor.fetchall() == [(2,)]


def test_rollbackignores_errors(backend_sqlite3):
    with migrations_dir(
        """
        step("CREATE TABLE yoyo_test (id INT)")
        step("INSERT INTO yoyo_test VALUES (1)",
            "DELETE FROM yoyo_test WHERE id=2")
        step("UPDATE yoyo_test SET id=2 WHERE id=1",
            "SELECT nonexistent FROM imaginary", ignore_errors='rollback')
        """
    ) as tmpdir:
        migrations = read_migrations(tmpdir)
        backend_sqlite3.apply_migrations(migrations)
        cursor = backend_sqlite3.cursor()
        cursor.execute("SELECT * FROM yoyo_test")
        assert cursor.fetchall() == [(2,)]

        backend_sqlite3.rollback_migrations(migrations)
        cursor.execute("SELECT * FROM yoyo_test")
        assert cursor.fetchall() == []


def test_migration_is_committed(backend):
    with migrations_dir('step("CREATE TABLE yoyo_test (id INT)")') as tmpdir:
        migrations = read_migrations(tmpdir)
        backend.apply_migrations(migrations)

        backend.rollback()
        rows = backend.execute("SELECT * FROM yoyo_test").fetchall()
        assert list(rows) == []


def test_rollback_happens_on_step_failure(backend):
    with migrations_dir(
        """
        step("",
                "CREATE TABLE yoyo_is_rolledback (i INT)"),
        step("CREATE TABLE yoyo_test (s VARCHAR(100))",
                "DROP TABLE yoyo_test")
        step("invalid sql!")
        """
    ) as tmpdir:
        migrations = read_migrations(tmpdir)
        with pytest.raises(backend.DatabaseError):
            backend.apply_migrations(migrations)

    # The yoyo_test table should have either been deleted (transactional ddl)
    # or dropped (non-transactional-ddl)
    with pytest.raises(backend.DatabaseError):
        backend.execute("SELECT * FROM yoyo_test")

    # Transactional DDL: rollback steps not executed
    if backend.has_transactional_ddl:
        with pytest.raises(backend.DatabaseError):
            backend.execute("SELECT * FROM yoyo_is_rolledback")

    # Non-transactional DDL: ensure the rollback steps were executed
    else:
        cursor = backend.execute("SELECT * FROM yoyo_is_rolledback")
        assert list(cursor.fetchall()) == []


def test_specify_migration_table(tmpdir, dburi):
    with migrations_dir(
        """
        step("CREATE TABLE yoyo_test (id INT)")
        step("DROP TABLE yoyo_test")
        """
    ) as tmpdir:
        backend = get_backend(dburi, migration_table="another_migration_table")
        migrations = read_migrations(tmpdir)
        backend.apply_migrations(migrations)
        cursor = backend.cursor()
        cursor.execute("SELECT migration_id FROM another_migration_table")
        assert list(cursor.fetchall()) == [("0",)]


def test_migration_functions_have_namespace_access(backend_sqlite3):
    """
    Test that functions called via step have access to the script namespace
    """
    with migrations_dir(
        """
        def foo(conn):
            conn.cursor().execute("CREATE TABLE foo_test (id INT)")
            conn.cursor().execute("INSERT INTO foo_test VALUES (1)")
        def bar(conn):
            foo(conn)
        step(bar)
        """
    ) as tmpdir:
        migrations = read_migrations(tmpdir)
        backend_sqlite3.apply_migrations(migrations)
        cursor = backend_sqlite3.cursor()
        cursor.execute("SELECT id FROM foo_test")
        assert cursor.fetchall() == [(1,)]


def test_migrations_can_import_step_and_group(backend_sqlite3):
    with migrations_dir(
        """
        from yoyo import group, step
        step("CREATE TABLE yoyo_test (id INT)")
        group(step("INSERT INTO yoyo_test VALUES (1)")),
        """
    ) as tmpdir:
        migrations = read_migrations(tmpdir)
        backend_sqlite3.apply_migrations(migrations)
        cursor = backend_sqlite3.cursor()
        cursor.execute("SELECT id FROM yoyo_test")
        assert cursor.fetchall() == [(1,)]


def test_migrations_display_selected_data(backend_sqlite3):
    with migrations_dir(
        """
        step("CREATE TABLE yoyo_test (id INT, c VARCHAR(1))")
        step("INSERT INTO yoyo_test VALUES (1, 'a')")
        step("INSERT INTO yoyo_test VALUES (2, 'b')")
        step("SELECT * FROM yoyo_test")
        """
    ) as tmpdir:
        migrations = read_migrations(tmpdir)
        with patch("yoyo.migrations.sys.stdout") as stdout:
            backend_sqlite3.apply_migrations(migrations)
            written = "".join(a[0] for a, kw in stdout.write.call_args_list)
            assert written == (
                " id | c \n" "----+---\n" " 1  | a \n" " 2  | b \n" "(2 rows)\n"
            )


def test_grouped_migrations_can_be_rolled_back(backend):
    with migrations_dir(
        a="from yoyo import step\n"
        'steps = [step("CREATE TABLE p (n INT)",'
        '              "DROP TABLE p")]'
    ) as t1:
        backend.apply_migrations(read_migrations(t1))

        with migrations_dir(
            b="from yoyo import group\n"
            "from yoyo import step\n"
            "steps = [\n"
            "    group(\n"
            '        step("INSERT INTO p VALUES (3)", \n'
            '             "DELETE FROM p WHERE n=3"),\n'
            '        step("UPDATE p SET n = n * 2", \n'
            '             "UPDATE p SET n = n / 2"),\n'
            '        step("UPDATE p SET n = n + 1", \n'
            '             "UPDATE p SET n = n - 1"),\n'
            "   )\n"
            "]\n"
        ) as t2:
            migrations = read_migrations(t2)
            backend.apply_migrations(migrations)
            backend.rollback_migrations(migrations)
            cursor = backend.execute("SELECT count(1) FROM p")
            assert cursor.fetchone() == (0,)
            backend.rollback()
        backend.rollback_migrations(read_migrations(t1))


class TestMigrationList(object):
    def test_can_create_empty(self):
        m = MigrationList()
        assert list(m) == []

    def test_cannot_create_with_duplicate_ids(self):
        with pytest.raises(exceptions.MigrationConflict):
            MigrationList([Mock(id=1), Mock(id=1)])

    def test_can_append_new_id(self):
        m = MigrationList([Mock(id=n) for n in range(10)])
        m.append(Mock(id=10))

    def test_cannot_append_duplicate_id(self):
        m = MigrationList([Mock(id=n) for n in range(10)])
        with pytest.raises(exceptions.MigrationConflict):
            m.append(Mock(id=1))

    def test_deletion_allows_reinsertion(self):
        m = MigrationList([Mock(id=n) for n in range(10)])
        del m[0]
        m.append(Mock(id=0))

    def test_can_overwrite_slice_with_same_ids(self):
        m = MigrationList([Mock(id=n) for n in range(10)])
        m[1:3] = [Mock(id=2), Mock(id=1)]

    def test_cannot_overwrite_slice_with_conflicting_ids(self):
        m = MigrationList([Mock(id=n) for n in range(10)])
        with pytest.raises(exceptions.MigrationConflict):
            m[1:3] = [Mock(id=4)]


class TestAncestorsDescendants(object):
    def setup_method(self):
        self.m1 = Mock(id="m1", depends=["m2", "m3"])
        self.m2 = Mock(id="m2", depends=["m3"])
        self.m3 = Mock(id="m3", depends=["m5"])
        self.m4 = Mock(id="m4", depends=["m5"])
        self.m5 = Mock(id="m5", depends=[])
        self.m1.depends = {self.m2, self.m3}
        self.m2.depends = {self.m3}
        self.m3.depends = {self.m5}
        self.m4.depends = {self.m5}
        self.migrations = {self.m1, self.m2, self.m3, self.m4, self.m5}

    def test_ancestors(self):

        assert ancestors(self.m1, self.migrations) == {
            self.m2,
            self.m3,
            self.m5,
        }
        assert ancestors(self.m2, self.migrations) == {self.m3, self.m5}
        assert ancestors(self.m3, self.migrations) == {self.m5}
        assert ancestors(self.m4, self.migrations) == {self.m5}
        assert ancestors(self.m5, self.migrations) == set()

    def test_descendants(self):

        assert descendants(self.m1, self.migrations) == set()
        assert descendants(self.m2, self.migrations) == {self.m1}
        assert descendants(self.m3, self.migrations) == {self.m2, self.m1}
        assert descendants(self.m4, self.migrations) == set()
        assert descendants(self.m5, self.migrations) == {
            self.m4,
            self.m3,
            self.m2,
            self.m1,
        }


class TestReadMigrations(object):
    def test_it_ignores_yoyo_new_tmp_files(self):
        """
        The yoyo new command creates temporary files in the migrations directory.
        These shouldn't be picked up by yoyo apply etc
        """
        with migrations_dir(**{newmigration.tempfile_prefix + "test": ""}) as tmpdir:
            assert len(read_migrations(tmpdir)) == 0

    def test_it_loads_post_apply_scripts(self):
        with migrations_dir(**{"post-apply": "step('SELECT 1')"}) as tmpdir:
            migrations = read_migrations(tmpdir)
            assert len(migrations) == 0
        assert len(migrations.post_apply) == 1

    def test_it_does_not_add_duplicate_steps(self):
        with migrations_dir("step('SELECT 1')") as tmpdir:
            m = read_migrations(tmpdir)[0]
            m.load()
            assert len(m.steps) == 1

            m = read_migrations(tmpdir)[0]
            m.load()
            assert len(m.steps) == 1

    def test_it_does_not_add_duplicate_steps_with_imported_symbols(self, tmpdir):
        with migrations_dir(a="from yoyo import step; step('SELECT 1')") as tmpdir:
            m = read_migrations(tmpdir)[0]
            m.load()
            assert len(m.steps) == 1

            m = read_migrations(tmpdir)[0]
            m.load()
            assert len(m.steps) == 1

    def test_it_reads_from_package_data(self):
        migrations = read_migrations("package:yoyo:tests/migrations")
        assert len(migrations) == 1
        assert migrations[0].id == "test-pkg-migration"

    def test_it_reads_relative_path(self):
        """
        https://todo.sr.ht/~olly/yoyo/79
        """
        with migrations_dir(a="from yoyo import step; step('SELECT 1')") as tmpdir:
            saved_cwd = os.getcwd()
            try:
                os.chdir(tmpdir)
                m = read_migrations(".")[0]
                m.load()
                assert len(m.steps) == 1
            finally:
                os.chdir(saved_cwd)

    def test_it_globs_directory_names(self):
        def touch(f):
            io.open(f, "w").close()

        with tempdir() as t:
            os.mkdir(os.path.join(t, "aa"))
            os.mkdir(os.path.join(t, "ab"))
            os.mkdir(os.path.join(t, "b"))
            touch(os.path.join(t, "aa", "1.py"))
            touch(os.path.join(t, "ab", "2.py"))
            touch(os.path.join(t, "b", "3.py"))

            migrations = read_migrations("{}/a*".format(t))
            migration_ids = [m.id for m in migrations]
            assert "1" in migration_ids
            assert "2" in migration_ids
            assert "3" not in migration_ids

    def test_it_loads_sql_migrations(self):
        mdir = migrations_dir(
            **{
                "1.sql": "CREATE TABLE foo (id int)",
                "1.rollback.sql": "DROP TABLE foo",
            }
        )
        with mdir as tmp:
            migrations = read_migrations(tmp)
            assert [m.id for m in migrations] == ["1"]
            m = migrations[0]
            m.load()
            assert m.steps[0].step._apply == "CREATE TABLE foo (id int)"
            assert m.steps[0].step._rollback == "DROP TABLE foo"

    def test_it_sets_transactional_for_sql_migrations(self):
        def check(sql, expected):
            with migrations_dir(**{"1.sql": sql}) as tmp:
                migration = read_migrations(tmp)[0]
                migration.load()
                assert migration.use_transactions is expected
                assert migration.steps[0].step._apply == "SELECT 1"

        check("SELECT 1", True)
        check("-- transactional: true\nSELECT 1", True)
        check("-- transactional: false\nSELECT 1", False)
        check("-- transactional: FALSE\nSELECT 1", False)
        check("-- transactional: FALSE\r\nSELECT 1", False)
        check("-- I like bananas!\n-- transactional: FALSE\nSELECT 1", False)

    def test_it_sets_docstring_for_sql_migrations(self):
        def check(sql, expected):
            with migrations_dir(**{"1.sql": sql}) as tmp:
                migration = read_migrations(tmp)[0]
                migration.load()
                assert migration.module.__doc__ == expected
                assert migration.steps[0].step._apply == "SELECT 1"

        check("SELECT 1", "")
        check("-- foo\n-- transactional: true\n--bar\nSELECT 1", "foo\nbar")

    def test_it_sets_depends_for_sql_migrations(self):
        def check(sql, expected):
            with migrations_dir(**{"1.sql": "", "2.sql": "", "3.sql": sql}) as tmp:

                migration = read_migrations(tmp)[-1]
                migration.load()
                assert {m.id for m in migration._depends} == expected
                assert migration.steps[0].step._apply == "SELECT 1"

        check("SELECT 1", set())
        check("-- depends: 1\nSELECT 1", {"1"})
        check("-- depends: 1 2\nSELECT 1", {"1", "2"})
        check("-- depends: 2\n-- depends : 1\nSELECT 1", {"1", "2"})
        with pytest.raises(exceptions.BadMigration):
            check("-- depends: true\nSELECT 1", set())

    def test_it_does_not_mix_up_migrations_from_different_sources(
        self, backend_sqlite3
    ):
        with migrations_dir(**{"1.sql": "", "3.sql": ""}) as t1, migrations_dir(
            **{"2.sql": "", "4.sql": ""}
        ) as t2:
            migrations = read_migrations(t1, t2)
            assert [m.id for m in backend_sqlite3.to_apply(migrations)] == [
                "1",
                "3",
                "2",
                "4",
            ]


class TestPostApplyHooks(object):
    def test_post_apply_hooks_are_run_every_time(self, backend_sqlite3):
        migrations = migrations_dir(
            **{
                "a": "step('create table postapply (i int)')",
                "post-apply": "step('insert into postapply values (1)')",
            }
        )

        with migrations as tmp:

            def count_postapply_calls():
                cursor = backend_sqlite3.cursor()
                cursor.execute("SELECT count(1) FROM postapply")
                return cursor.fetchone()[0]

            def _apply_migrations():
                backend_sqlite3.apply_migrations(
                    backend_sqlite3.to_apply(read_migrations(tmp))
                )

            # Should apply migration 'a' and call the post-apply hook
            _apply_migrations()
            assert count_postapply_calls() == 1

            # No outstanding migrations: post-apply hook should not be called
            _apply_migrations()
            assert count_postapply_calls() == 1

            # New migration added: post-apply should be called a second time
            migrations.add_migration("b", "")
            _apply_migrations()
            assert count_postapply_calls() == 2

    def test_it_runs_multiple_post_apply_hooks(self, backend_sqlite3):
        with migrations_dir(
            **{
                "a": "step('create table postapply (i int)')",
                "post-apply": "step('insert into postapply values (1)')",
                "post-apply2": "step('insert into postapply values (2)')",
            }
        ) as tmpdir:
            backend_sqlite3.apply_migrations(
                backend_sqlite3.to_apply(read_migrations(tmpdir))
            )
            cursor = backend_sqlite3.cursor()
            cursor.execute("SELECT * FROM postapply")
            assert cursor.fetchall() == [(1,), (2,)]

    def test_apply_migrations_only_does_not_run_hooks(self, backend_sqlite3):
        with migrations_dir(
            **{
                "a": "step('create table postapply (i int)')",
                "post-apply": "step('insert into postapply values (1)')",
            }
        ) as tmpdir:
            backend_sqlite3.apply_migrations_only(
                backend_sqlite3.to_apply(read_migrations(tmpdir))
            )
            cursor = backend_sqlite3.cursor()
            cursor.execute("SELECT * FROM postapply")
            assert cursor.fetchall() == []


class TestLogging(object):
    def get_last_log_entry(self, backend):
        cursor = backend.execute(
            "SELECT migration_id, operation, "
            "created_at_utc, username, hostname "
            "from _yoyo_log "
            "ORDER BY id DESC LIMIT 1"
        )
        return {d[0]: value for d, value in zip(cursor.description, cursor.fetchone())}

    def get_log_count(self, backend):
        return backend.execute("SELECT count(1) FROM _yoyo_log").fetchone()[0]

    def test_it_logs_apply_and_rollback(self, backend):
        with migrations_dir(a='step("CREATE TABLE yoyo_test (id INT)")') as tmpdir:
            migrations = read_migrations(tmpdir)
            backend.apply_migrations(migrations)
            assert self.get_log_count(backend) == 1
            logged = self.get_last_log_entry(backend)
            assert logged["migration_id"] == "a"
            assert logged["operation"] == "apply"
            assert logged["created_at_utc"] >= datetime.utcnow() - timedelta(seconds=3)
            apply_time = logged["created_at_utc"]

            backend.rollback_migrations(migrations)
            assert self.get_log_count(backend) == 2
            logged = self.get_last_log_entry(backend)
            assert logged["migration_id"] == "a"
            assert logged["operation"] == "rollback"
            assert logged["created_at_utc"] >= apply_time

    def test_it_logs_mark_and_unmark(self, backend):
        with migrations_dir(a='step("CREATE TABLE yoyo_test (id INT)")') as tmpdir:
            migrations = read_migrations(tmpdir)
            backend.mark_migrations(migrations)
            assert self.get_log_count(backend) == 1
            logged = self.get_last_log_entry(backend)
            assert logged["migration_id"] == "a"
            assert logged["operation"] == "mark"
            assert logged["created_at_utc"] >= datetime.utcnow() - timedelta(seconds=3)
            marked_time = logged["created_at_utc"]

            backend.unmark_migrations(migrations)
            assert self.get_log_count(backend) == 2
            logged = self.get_last_log_entry(backend)
            assert logged["migration_id"] == "a"
            assert logged["operation"] == "unmark"
            assert logged["created_at_utc"] >= marked_time
