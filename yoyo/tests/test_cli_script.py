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

from shutil import rmtree
from datetime import datetime
from tempfile import mkdtemp
from functools import partial
from itertools import count
import pathlib
import io
import os
import os.path
import re
import sys
import textwrap

from unittest.mock import Mock, patch, call
import freezegun
import pytest
import tms

from yoyo import read_migrations
from yoyo.config import get_configparser
from yoyo.tests import dburi_sqlite3
from yoyo.tests import migrations_dir
from yoyo.tests import get_backend
from yoyo.scripts.main import main, parse_args, LEGACY_CONFIG_FILENAME
from yoyo.scripts import newmigration


def is_tmpfile(p, directory=None):
    return (p.startswith(directory) if directory else True) and os.path.basename(
        p
    ).startswith(newmigration.tempfile_prefix)


class TestInteractiveScript(object):
    def setup_method(self):
        self.stdout_tty_patch = patch("sys.stdout.isatty", return_value=True)
        self.stdout_tty_patch.start()
        self.confirm_patch = patch("yoyo.utils.confirm", return_value=False)
        self.confirm = self.confirm_patch.start()
        self.prompt_patch = patch("yoyo.utils.prompt", return_value="n")
        self.prompt = self.prompt_patch.start()
        self.tmpdir = mkdtemp()
        self.dburi = "sqlite:///" + self.tmpdir + "db.sqlite"
        self.saved_cwd = os.getcwd()
        os.chdir(self.tmpdir)

    def teardown_method(self):
        self.prompt_patch.stop()
        self.confirm_patch.stop()
        self.stdout_tty_patch.stop()
        os.chdir(self.saved_cwd)
        rmtree(self.tmpdir)

    def writeconfig(self, **defaults):
        cp = get_configparser()
        for item in defaults:
            cp.set("DEFAULT", item, defaults[item])

        if sys.version_info < (3, 0):
            with open("yoyo.ini", "w") as f:
                cp.write(f)
        else:
            with open("yoyo.ini", "w", encoding="UTF-8") as f:
                cp.write(f)

    def get_migration_log(self):
        return (
            get_backend(self.dburi)
            .execute("SELECT migration_id, operation FROM _yoyo_log")
            .fetchall()
        )


class TestYoyoScript(TestInteractiveScript):
    def test_it_sets_verbosity_level(self, tmpdir):
        with patch("yoyo.scripts.main.configure_logging") as m:
            main(["apply", str(tmpdir), "--database", dburi_sqlite3])
            assert m.call_args == call(0)
            main(["-vvv", "apply", str(tmpdir), "--database", dburi_sqlite3])
            assert m.call_args == call(3)

    def test_it_prompts_to_create_config_file(self, tmpdir):
        main(["apply", str(tmpdir), "--database", dburi_sqlite3])
        assert "save migration config" in self.confirm.call_args[0][0].lower()

    def test_it_creates_config_file(self, tmpdir):
        self.confirm.return_value = True
        main(["apply", str(tmpdir), "--database", dburi_sqlite3])
        assert os.path.exists("yoyo.ini")
        with open("yoyo.ini") as f:
            assert "database = {0}".format(dburi_sqlite3) in f.read()

    def test_it_uses_config_file(self, tmpdir):
        self.writeconfig(batch_mode="on")
        with patch("yoyo.scripts.migrate.apply") as apply:
            main(["apply", str(tmpdir), "--database", dburi_sqlite3])
            args_used = apply.call_args[0][0]
            assert args_used.batch_mode is True

    def test_it_ignores_config_file(self, tmpdir):
        self.writeconfig(batch_mode="on")
        with patch("yoyo.scripts.migrate.apply") as apply:
            main(
                [
                    "apply",
                    "--no-config-file",
                    str(tmpdir),
                    "--database",
                    dburi_sqlite3,
                ]
            )
            args_used = apply.call_args[0][0]
            assert args_used.batch_mode is False

    def test_it_prompts_password(self, tmpdir):
        dburi = "sqlite://user@/:memory"
        with patch("yoyo.scripts.main.getpass", return_value="fish") as getpass, patch(
            "yoyo.connections.get_backend"
        ) as get_backend:
            main(["apply", str(tmpdir), "--database", dburi, "--prompt-password"])
            assert getpass.call_count == 1
            assert get_backend.call_args == call(
                "sqlite://user:fish@/:memory", "_yoyo_migration"
            )

    def test_it_prompts_migrations(self, tmpdir):
        with patch(
            "yoyo.scripts.migrate.prompt_migrations"
        ) as prompt_migrations, patch(
            "yoyo.scripts.migrate.get_backend"
        ) as get_backend:
            main(["apply", str(tmpdir), "--database", dburi_sqlite3])
            migrations = get_backend().to_apply()
            assert migrations in prompt_migrations.call_args[0]

    def test_it_applies_migrations(self, tmpdir):
        with patch("yoyo.scripts.migrate.get_backend") as get_backend:
            main(["-b", "apply", str(tmpdir), "--database", dburi_sqlite3])
            assert get_backend().rollback_migrations.call_count == 0
            assert get_backend().apply_migrations.call_count == 1

    def test_it_rollsback_migrations(self, tmpdir):
        with patch("yoyo.scripts.migrate.get_backend") as get_backend:
            main(["-b", "rollback", str(tmpdir), "--database", dburi_sqlite3])
            assert get_backend().rollback_migrations.call_count == 1
            assert get_backend().apply_migrations.call_count == 0

    def test_it_reapplies_migrations(self, tmpdir):
        with patch("yoyo.scripts.migrate.get_backend") as get_backend:
            main(["-b", "reapply", str(tmpdir), "--database", dburi_sqlite3])
            assert get_backend().rollback_migrations.call_count == 1
            assert get_backend().apply_migrations.call_count == 1

    def test_it_applies_from_multiple_sources(self):
        with migrations_dir(
            m1='step("CREATE TABLE yoyo_test1 (id INT)")'
        ) as t1, migrations_dir(
            m2='step("CREATE TABLE yoyo_test2 (id INT)")'
        ) as t2, patch(
            "yoyo.backends.DatabaseBackend.apply_migrations"
        ) as apply:
            main(["-b", "apply", t1, t2, "--database", dburi_sqlite3])
            call_posargs, call_kwargs = apply.call_args
            migrations, _ = call_posargs
            assert [m.path for m in migrations] == [
                os.path.join(t1, "m1.py"),
                os.path.join(t2, "m2.py"),
            ]

    def test_it_offers_to_upgrade(self, tmpdir):
        legacy_config_path = os.path.join(str(tmpdir), LEGACY_CONFIG_FILENAME)
        with open(legacy_config_path, "w", encoding="utf-8") as f:
            f.write("[DEFAULT]\n")
            f.write("migration_table=_yoyo_migration\n")
            f.write("dburi=sqlite:///\n")

        self.confirm.return_value = True
        main(["apply", str(tmpdir)])
        prompts = [args[0].lower() for args, kwargs in self.confirm.call_args_list]
        assert len(prompts) == 2
        assert prompts[0].startswith("move legacy configuration")
        assert prompts[1].startswith("delete legacy configuration")
        assert not os.path.exists(legacy_config_path)

        with open("yoyo.ini", "r") as f:
            config = f.read()
            assert "database = sqlite:///\n" in config
            assert "migration_table = _yoyo_migration\n" in config
            assert "batch_mode = off\n" in config
            assert "verbosity = 0\n" in config

    def test_it_upgrades_migration_table_None(self, tmpdir):
        legacy_config_path = os.path.join(str(tmpdir), LEGACY_CONFIG_FILENAME)
        with open(legacy_config_path, "w", encoding="utf-8") as f:
            f.write("[DEFAULT]\n")
            f.write("migration_table=None\n")
            f.write("dburi=sqlite:///\n")
        self.confirm.return_value = True
        main(["apply", str(tmpdir)])

        with open("yoyo.ini", "r") as f:
            config = f.read()
        assert "migration_table = _yoyo_migration\n" in config

    def test_it_forces_batch_mode_if_not_running_in_a_tty(self, tmpdir):
        with patch("sys.stdout", isatty=lambda: False):
            main(["apply", str(tmpdir), "--database", dburi_sqlite3])
            assert self.prompt.call_count == 0
            assert self.confirm.call_count == 0

    def test_concurrent_instances_do_not_conflict(self, backend):
        import threading
        from functools import partial

        if backend.uri.scheme == "sqlite":
            pytest.skip("Concurrency tests not supported for sqlite databases")

        with migrations_dir(
            m1=(
                "import time\n"
                "step(lambda conn: time.sleep(0.1))\n"
                "step(\"INSERT INTO yoyo_t VALUES ('A')\")"
            )
        ) as tmpdir:
            assert "yoyo_t" in backend.list_tables()
            backend.rollback()
            backend.execute("SELECT * FROM yoyo_t")
            run_migrations = partial(
                main, ["apply", "-b", tmpdir, "--database", str(backend.uri)]
            )
            threads = [threading.Thread(target=run_migrations) for ix in range(20)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()

            # Exactly one instance of the migration script should have succeeded
            backend.rollback()
            cursor = backend.execute("SELECT COUNT(1) from yoyo_t")
            assert cursor.fetchone()[0] == 1

    def test_it_breaks_lock(self, dburi):
        if dburi.startswith("sqlite"):
            pytest.skip("Test not supported for sqlite databases")
        backend = get_backend(dburi)
        backend.execute(
            "INSERT INTO yoyo_lock (locked, ctime, pid) " "VALUES (1, :now, 1)",
            {"now": datetime.utcnow()},
        )
        backend.commit()
        main(["break-lock", "--database", dburi])
        lock_count = backend.execute("SELECT COUNT(1) FROM yoyo_lock").fetchone()[0]
        assert lock_count == 0

    def test_it_prompts_password_on_break_lock(self):
        dburi = "sqlite://user@/:memory"
        with patch("yoyo.scripts.main.getpass", return_value="fish") as getpass, patch(
            "yoyo.connections.get_backend"
        ) as get_backend:
            main(["break-lock", "--database", dburi, "--prompt-password"])
            assert getpass.call_count == 1
            assert get_backend.call_args == call(
                "sqlite://user:fish@/:memory", "_yoyo_migration"
            )


class TestArgParsing(TestInteractiveScript):
    def test_it_uses_config_file_defaults(self):
        self.writeconfig(
            sources="/tmp/migrations",
            database="postgresql:///foo",
            migration_table="my_migrations",
        )
        _, _, args = parse_args(["apply"])
        assert args.database == "postgresql:///foo"
        assert args.sources == ["/tmp/migrations"]
        assert args.migration_table == "my_migrations"

    def test_it_uses_interpolated_values_from_config(self):
        self.writeconfig(sources="%(here)s/migrations")
        _, _, args = parse_args(["apply"])
        assert args.sources == [os.getcwd() + "/migrations"]

    def test_cli_args_take_precendence(self):
        self.writeconfig(sources="A")
        _, _, args = parse_args(["apply", "B", "--database", "C"])
        assert args.sources == ["B"]

    def test_global_args_can_appear_before_command(self):
        _, _, args = parse_args(["apply", "X", "--database", "Y"])
        assert args.verbosity == 0
        _, _, args = parse_args(["-v", "apply", "X", "--database", "Y"])
        assert args.verbosity == 1

    def test_global_args_can_appear_after_command(self):
        _, _, args = parse_args(["apply", "X", "Y"])
        assert args.verbosity == 0
        _, _, args = parse_args(["apply", "-v", "X", "Y"])
        assert args.verbosity == 1


class TestMarkCommand(TestInteractiveScript):
    def test_it_prompts_only_unapplied(self):
        with migrations_dir(
            m1='step("CREATE TABLE test1 (id INT)")',
            m2='step("CREATE TABLE test2 (id INT)")',
            m3='step("CREATE TABLE test3 (id INT)")',
        ) as tmpdir:
            from yoyo.connections import get_backend

            migrations = read_migrations(tmpdir)
            backend = get_backend(self.dburi)
            backend.apply_migrations(migrations[:1])

            with patch("yoyo.scripts.migrate.prompt_migrations") as prompt_migrations:
                main(["mark", tmpdir, "--database", self.dburi])
                _, prompted, _ = prompt_migrations.call_args[0]
                prompted = [m.id for m in prompted]
                assert prompted == ["m2", "m3"]

    def test_it_marks_at_selected_version(self):
        with migrations_dir(
            m1='step("INSERT INTO t VALUES (1)")',
            m2='__depends__=["m1"]; step("INSERT INTO t VALUES (2)")',
            m3='step("INSERT INTO t VALUES (2)")',
        ) as tmpdir:
            from yoyo.connections import get_backend

            self.confirm.return_value = True
            migrations = read_migrations(tmpdir)
            backend = get_backend(self.dburi)
            with backend.transaction():
                backend.execute("CREATE TABLE t (id INT)")

            main(["mark", "-r", "m2", tmpdir, "--database", self.dburi])
            assert backend.is_applied(migrations[0])
            assert backend.is_applied(migrations[1])
            assert not backend.is_applied(migrations[2])

            # Check that migration steps have not been applied
            c = backend.execute("SELECT * FROM t")
            assert len(c.fetchall()) == 0


class TestUnmarkCommand(TestInteractiveScript):
    def test_it_prompts_only_applied(self):
        with migrations_dir(m1="", m2="", m3="") as tmpdir:
            from yoyo.connections import get_backend

            migrations = read_migrations(tmpdir)
            backend = get_backend(self.dburi)
            backend.apply_migrations(migrations[:2])
            assert len(backend.get_applied_migration_hashes()) == 2

            with patch("yoyo.scripts.migrate.prompt_migrations") as prompt_migrations:
                main(["unmark", tmpdir, "--database", self.dburi])
                _, prompted, _ = prompt_migrations.call_args[0]
                prompted = [m.id for m in prompted]
                assert prompted == ["m2", "m1"]

    def test_it_unmarks_to_selected_revision(self):
        with migrations_dir(
            m1="", m2='__depends__=["m1"]', m3='__depends__=["m2"]'
        ) as tmpdir:
            from yoyo.connections import get_backend

            self.confirm.return_value = True
            migrations = read_migrations(tmpdir)
            backend = get_backend(self.dburi)
            backend.apply_migrations(migrations)

            main(["unmark", "-r", "m2", tmpdir, "--database", self.dburi])
            assert backend.is_applied(migrations[0])
            assert not backend.is_applied(migrations[1])
            assert not backend.is_applied(migrations[2])


class TestNewMigration(TestInteractiveScript):
    def setup_method(self):
        def mockstat(f, c=count()):
            return Mock(st_mtime=next(c))

        super(TestNewMigration, self).setup_method()
        self.subprocess_patch = patch("yoyo.scripts.newmigration.subprocess")
        self.subprocess = self.subprocess_patch.start()
        self.subprocess.call.return_value = 0
        self.stat_patch = patch("yoyo.scripts.newmigration.stat", mockstat)
        self.stat_patch.start()

    def teardown_method(self):
        super(TestNewMigration, self).teardown_method()
        self.subprocess_patch.stop()
        self.stat_patch.stop()

    def test_it_creates_an_empty_migration(self, tmpdir):
        main(["new", "-b", "-m", "foo", str(tmpdir), "--database", dburi_sqlite3])
        assert any("-foo.py" in f for f in os.listdir(str(tmpdir)))

    def test_it_depends_on_all_current_heads(self):
        with migrations_dir(
            m1="", m2='__depends__=["m1"]; step("INSERT INTO t VALUES (2)")', m3=""
        ) as tmpdir:
            main(["new", "-b", "-m", "foo", tmpdir, "--database", dburi_sqlite3])
            m = next(f for f in os.listdir(tmpdir) if "-foo.py" in f)
            with open(os.path.join(tmpdir, m), encoding="utf-8") as f:
                assert "__depends__ = {'m2', 'm3'}" in f.read()

    def test_it_names_file_by_date_and_sequence(self, tmpdir):
        with freezegun.freeze_time("2001-1-1"):
            main(["new", "-b", "-m", "foo", str(tmpdir), "--database", dburi_sqlite3])
            main(["new", "-b", "-m", "bar", str(tmpdir), "--database", dburi_sqlite3])
        names = [n for n in sorted(os.listdir(str(tmpdir))) if n.endswith(".py")]
        assert names[0].startswith("20010101_01_")
        assert names[0].endswith("-foo.py")
        assert names[1].startswith("20010101_02_")
        assert names[1].endswith("-bar.py")

    def test_it_invokes_correct_editor_binary_from_config(self, tmpdir):
        self.writeconfig(editor="vim {} -c +10")
        main(["new", str(tmpdir), "--database", dburi_sqlite3])
        assert self.subprocess.call.call_args == call(
            [
                "vim",
                tms.Matcher(partial(is_tmpfile, directory=str(tmpdir))),
                "-c",
                "+10",
            ]
        )

    def test_it_invokes_correct_editor_binary_from_env(self, tmpdir):
        # default to $VISUAL
        with patch("os.environ", {"EDITOR": "ed", "VISUAL": "visualed"}):
            main(["new", str(tmpdir), "--database", dburi_sqlite3])
            assert self.subprocess.call.call_args == call(["visualed", tms.Unicode()])

        # fallback to $EDITOR
        with patch("os.environ", {"EDITOR": "ed"}):
            main(["new", str(tmpdir), "--database", dburi_sqlite3])
            assert self.subprocess.call.call_args == call(["ed", tms.Unicode()])

        # Otherwise, vi
        with patch("os.environ", {}):
            main(["new", str(tmpdir), "--database", dburi_sqlite3]) == call(
                ["vi", tms.Unicode()]
            )

        # Prompts should only appear if there is an error reading the migration
        # file, which should not be the case.
        assert self.prompt.call_args_list == []

    def test_it_pulls_message_from_docstring(self, tmpdir):
        def write_migration(argv):
            with open(argv[-1], "w", encoding="utf8") as f:
                f.write('"""\ntest docstring\nsplit over\n\nlines\n"""\n')

        self.subprocess.call = write_migration
        main(["new", str(tmpdir), "--database", dburi_sqlite3])
        names = [n for n in sorted(os.listdir(str(tmpdir))) if n.endswith(".py")]
        assert "test-docstring" in names[0]

    def test_it_prompts_to_reedit_bad_migration(self, tmpdir):
        def write_migration(argv):
            with open(argv[-1], "w", encoding="utf8") as f:
                f.write("this is not valid python!")

        self.subprocess.call = write_migration
        main(["new", str(tmpdir), "--database", dburi_sqlite3])
        prompts = [args[0].lower() for args, kwargs in self.prompt.call_args_list]
        assert "retry editing?" in prompts[0]

    def test_it_defaults_docstring_to_message(self, tmpdir):
        main(
            [
                "new",
                "-b",
                "-m",
                "your ad here",
                str(tmpdir),
                "--database",
                dburi_sqlite3,
            ]
        )
        names = [n for n in sorted(os.listdir(tmpdir)) if n.endswith(".py")]
        with open(os.path.join(str(tmpdir), names[0]), "r", encoding="utf-8") as f:
            assert "your ad here" in f.read()

    def test_it_calls_post_create_command(self, tmpdir):
        self.writeconfig(post_create_command="/bin/ls -l {} {}")
        with freezegun.freeze_time("2001-1-1"):
            main(["new", "-b", str(tmpdir), "--database", dburi_sqlite3])
        is_filename = tms.Str(lambda s: os.path.basename(s).startswith("20010101_01_"))
        assert self.subprocess.call.call_args == call(
            ["/bin/ls", "-l", is_filename, is_filename]
        )

    def test_it_uses_configured_prefix(self, tmpdir):
        self.writeconfig(prefix="foo_")
        main(["new", "-b", "-m", "bar", str(tmpdir), "--database", dburi_sqlite3])
        names = [n for n in sorted(os.listdir(str(tmpdir))) if n.endswith(".py")]
        assert re.match("foo_.*-bar", names[0]) is not None

    def test_it_creates_sql_file(self):
        with migrations_dir(m1="") as tmpdir:
            main(
                [
                    "new",
                    "-b",
                    "-m",
                    "comment",
                    "--sql",
                    tmpdir,
                    "--database",
                    dburi_sqlite3,
                ]
            )
            name = next(n for n in sorted(os.listdir(tmpdir)) if n.endswith(".sql"))
            with open(os.path.join(tmpdir, name), "r", encoding="utf-8") as f:
                assert f.read() == textwrap.dedent(
                    """\
                    -- comment
                    -- depends: m1

                    """
                )


class TestList(TestInteractiveScript):
    def get_output(self, migrations):
        with migrations_dir(**migrations) as tmpdir:
            with patch("sys.stdout", io.StringIO()) as captured:
                main(["list", tmpdir, "--database", dburi_sqlite3])
            return captured.getvalue()

    def test_it_lists_migrations(self):
        output = self.get_output({"m1": "", "m2": ""})
        assert re.search(r"^U\s+m1", output, re.M)
        assert re.search(r"^U\s+m2", output, re.M)


class TestDevelopCommand(TestInteractiveScript):
    def test_it_applies_outstanding_migrations(self):
        with migrations_dir(m1="", m2="") as tmpdir:
            main(["develop", tmpdir, "--database", self.dburi])
            assert self.get_migration_log() == [
                ("m1", "apply"),
                ("m2", "apply"),
            ]

    def test_it_reapplies_last_migration(self):
        with migrations_dir(
            m1='step("CREATE TABLE yoyo_test1 (id INT)", "DROP TABLE yoyo_test1")',
            m2='step("CREATE TABLE yoyo_test2 (id INT)", "DROP TABLE yoyo_test2")',
        ) as tmpdir:
            main(["-b", "apply", tmpdir, "--database", self.dburi])
            assert self.get_migration_log() == [
                ("m1", "apply"),
                ("m2", "apply"),
            ]
            main(["develop", tmpdir, "--database", self.dburi])
            assert self.get_migration_log() == [
                ("m1", "apply"),
                ("m2", "apply"),
                ("m2", "rollback"),
                ("m2", "apply"),
            ]

    def test_it_reapplies_last_n_migrations(self):
        with migrations_dir(
            m1='step("CREATE TABLE yoyo_test1 (id INT)", "DROP TABLE yoyo_test1")',
            m2='step("CREATE TABLE yoyo_test2 (id INT)", "DROP TABLE yoyo_test2")',
        ) as tmpdir:
            main(["-b", "apply", tmpdir, "--database", self.dburi])
            assert self.get_migration_log() == [
                ("m1", "apply"),
                ("m2", "apply"),
            ]
            main(["develop", tmpdir, "-n", "2", "--database", self.dburi])
            assert self.get_migration_log() == [
                ("m1", "apply"),
                ("m2", "apply"),
                ("m2", "rollback"),
                ("m1", "rollback"),
                ("m1", "apply"),
                ("m2", "apply"),
            ]


class TestInitCommand(TestInteractiveScript):
    def test_it_creates_project(self):
        main(["-b", "init", "migrations", "--database", "sqlite://foo"])
        config = (pathlib.Path(self.tmpdir) / "yoyo.ini").read_text()
        assert "database = sqlite://foo" in config
        assert "sources = migrations" in config
        assert (pathlib.Path(self.tmpdir) / "migrations").is_dir()

    def test_it_doesnt_overwrite(self):
        configfile = pathlib.Path(self.tmpdir) / "yoyo.ini"
        configfile.write_text("[existing file]")
        main(["-b", "init", "migrations", "--database", "sqlite://foo"])
        assert "database = sqlite://foo" not in configfile.read_text()
        assert "existing file" in configfile.read_text()
        assert not (pathlib.Path(self.tmpdir) / "migrations").exists()

    def test_it_doesnt_prompt(self):
        with patch("yoyo.scripts.main.prompt_save_config") as prompt_save_config:
            main(["-b", "init", "migrations", "--database", "sqlite://foo"])
            assert prompt_save_config.called is False
