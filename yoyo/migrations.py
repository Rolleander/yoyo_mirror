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

from collections import Counter
from collections import OrderedDict
from collections import abc
from collections import defaultdict
from copy import copy
from glob import glob
from itertools import chain
from itertools import count
from itertools import zip_longest
from logging import getLogger
from typing import Dict
from typing import Iterable
from typing import List
from typing import Mapping
from typing import Tuple
import hashlib
import importlib.util
import os
import re
import sys
import inspect
import types
import textwrap
import weakref

import pkg_resources
import sqlparse

from yoyo import exceptions
from yoyo.utils import plural

logger = getLogger("yoyo.migrations")
default_migration_table = "_yoyo_migration"

hash_function = hashlib.sha256

_collectors = (
    weakref.WeakValueDictionary()
)  # type: Mapping[str, "StepCollector"]


def _is_migration_file(path):
    """
    Return True if the given path matches a migration file pattern
    """
    from yoyo.scripts import newmigration

    _, extension = os.path.splitext(path)
    return extension in {".py", ".sql"} and not path.startswith(
        newmigration.tempfile_prefix
    )


def get_migration_hash(migration_id):
    """
    Return a unique hash given a migration_id, that can be used as a database
    key.

    :param migration_id: a migration id (ie filename without extension), or
                         ``None`` if this is a new migration
    """
    if migration_id is None:
        return None
    return hash_function(migration_id.encode("utf-8")).hexdigest()


# eg: "-- depends: 1 2"
DirectivesType = Dict[str, str]

LeadingCommentType = str

SqlType = str


def parse_metadata_from_sql_comments(
    s: str,
) -> Tuple[DirectivesType, LeadingCommentType, SqlType]:
    directive_names = ["transactional", "depends"]
    comment_or_empty = re.compile(r"^(\s*|\s*--.*)$").match
    directive_pattern = re.compile(
        r"^\s*--\s*({})\s*:\s*(.*)$".format(
            "|".join(map(re.escape, directive_names))
        )
    )

    lineending = re.search(r"\n|\r\n|\r", s + "\n").group(0)  # type: ignore
    lines = iter(s.split(lineending))
    directives = {}  # type: DirectivesType
    leading_comments = []
    sql = []
    for line in lines:
        match = directive_pattern.match(line)
        if match:
            k, v = match.groups()
            if k in directives:
                directives[k] += " {}".format(v)
            else:
                directives[k] = v
        elif comment_or_empty(line):
            decommented = line.strip().lstrip("--").strip()
            leading_comments.append(decommented)
        else:
            sql.append(line)
            break
    sql.extend(lines)
    return (
        directives,
        textwrap.dedent(lineending.join(leading_comments)),
        lineending.join(sql),
    )


def read_sql_migration(
    path: str,
) -> Tuple[DirectivesType, LeadingCommentType, List[str]]:
    directives = {}  # type: DirectivesType
    leading_comment = ""
    statements = []
    if os.path.exists(path):
        with open(path, "r", encoding="UTF-8") as f:
            statements = sqlparse.split(f.read())
            if statements:
                (
                    directives,
                    leading_comment,
                    sql,
                ) = parse_metadata_from_sql_comments(statements[0])
                statements[0] = sql
    statements = [s for s in statements if s.strip()]
    return directives, leading_comment, statements


class Migration(object):

    __all_migrations = {}  # type: Dict[str, "Migration"]

    def __init__(self, id, path, source_dir):
        self.id = id
        self.hash = get_migration_hash(id)
        self.path = path
        self.steps = None
        self.source = None
        self.source_dir = source_dir
        self.use_transactions = True
        self._depends = None
        self.__all_migrations[id] = self
        self.module = None

    def __repr__(self):
        return "<{} {!r} from {}>".format(
            self.__class__.__name__, self.id, self.path
        )

    def is_raw_sql(self):
        return self.path.endswith(".sql")

    @property
    def loaded(self):
        return self.steps is not None

    @property
    def depends(self):
        self.load()
        return self._depends

    def load(self):
        if self.loaded:
            return

        collector = StepCollector(migration=self)
        _collectors[self.path] = collector
        with open(self.path, "r") as f:
            self.source = f.read()

        if self.is_raw_sql():
            self.module = types.ModuleType(self.path)
        else:
            spec = importlib.util.spec_from_file_location(self.path, self.path)
            self.module = importlib.util.module_from_spec(spec)

        self.module.step = collector.add_step  # type: ignore
        self.module.group = collector.add_step_group  # type: ignore
        self.module.transaction = collector.add_step_group  # type: ignore
        self.module.collector = collector  # type: ignore
        if self.is_raw_sql():
            directives, leading_comment, statements = read_sql_migration(
                self.path
            )
            _, _, rollback_statements = read_sql_migration(
                os.path.splitext(self.path)[0] + ".rollback.sql"
            )
            rollback_statements.reverse()
            statements_with_rollback = zip_longest(
                statements, rollback_statements, fillvalue=None
            )

            for s, r in statements_with_rollback:
                self.module.collector.add_step(s, r)  # type: ignore
            self.module.__doc__ = leading_comment
            self.module.__transactional__ = {"true": True, "false": False}[  # type: ignore
                directives.get("transactional", "true").lower()
            ]
            self.module.__depends__ = {  # type: ignore
                d for d in directives.get("depends", "").split() if d
            }

        else:
            try:
                spec.loader.exec_module(self.module)

            except Exception as e:
                logger.exception(
                    "Could not import migration from %r: %r", self.path, e
                )
                raise exceptions.BadMigration(self.path, e)
        depends = getattr(self.module, "__depends__", [])
        if isinstance(depends, (str, bytes)):
            depends = [depends]
        self._depends = {self.__all_migrations.get(id, None) for id in depends}
        self.use_transactions = getattr(self.module, "__transactional__", True)
        if None in self._depends:
            raise exceptions.BadMigration(
                "Could not resolve dependencies in {}".format(self.path)
            )
        self.steps = collector.create_steps(self.use_transactions)

    def process_steps(self, backend, direction, force=False):

        self.load()
        reverse = {"rollback": "apply", "apply": "rollback"}[direction]

        steps = self.steps
        if direction == "rollback":
            steps = reversed(steps)  # type: ignore

        executed_steps = []
        if self.use_transactions:
            transaction = backend.transaction
        else:
            transaction = backend.disable_transactions

        with transaction():
            for step in steps:
                try:
                    getattr(step, direction)(backend, force)
                    executed_steps.append(step)
                except backend.DatabaseError:
                    exc_info = sys.exc_info()

                    if (
                        not backend.has_transactional_ddl
                        or not self.use_transactions
                    ):
                        # Any DDL statements that have been executed have been
                        # committed. Go through the rollback steps to undo
                        # these inasmuch is possible.
                        try:
                            for step in reversed(executed_steps):
                                getattr(step, reverse)(backend)
                        except backend.DatabaseError:
                            logger.exception(
                                "Could not %s step %s", direction, step.id
                            )
                    if exc_info[1]:
                        raise exc_info[1].with_traceback(exc_info[2])


class PostApplyHookMigration(Migration):
    """
    A special migration that is run after successfully applying a set of
    migrations. Unlike a normal migration this will be run every time
    migrations are applied script is called.
    """


class StepBase(object):

    id = None

    def __repr__(self):
        return "<{} #{}>".format(self.__class__.__name__, self.id)

    def apply(self, backend, force=False):
        raise NotImplementedError()

    def rollback(self, backend, force=False):
        raise NotImplementedError()


class TransactionWrapper(StepBase):
    """
    A :class:~`yoyo.migrations.TransactionWrapper` object causes a step to be
    run within a single database transaction. Nested transactions are
    implemented via savepoints.
    """

    def __init__(self, step, ignore_errors=None):
        assert ignore_errors in (None, "all", "apply", "rollback")
        self.step = step
        self.ignore_errors = ignore_errors

    def __repr__(self):
        return "<TransactionWrapper {!r}>".format(self.step)

    def apply(self, backend, force=False, direction="apply"):
        with backend.transaction() as transaction:
            try:
                getattr(self.step, direction)(backend, force)
            except backend.DatabaseError:
                if force or self.ignore_errors in (direction, "all"):
                    logger.exception("Ignored error in %r", self.step)
                    transaction.rollback()
                    return
                else:
                    raise

    def rollback(self, backend, force=False):
        self.apply(backend, force, "rollback")


class Transactionless(StepBase):
    """
    A :class:~`yoyo.migrations.TransactionWrapper` object causes a step to be
    run outside of a database transaction.
    """

    def __init__(self, step, ignore_errors=None):
        assert ignore_errors in (None, "all", "apply", "rollback")
        self.step = step
        self.ignore_errors = ignore_errors

    def __repr__(self):
        return "<TransactionWrapper {!r}>".format(self.step)

    def apply(self, backend, force=False, direction="apply"):
        try:
            getattr(self.step, direction)(backend, force)
        except backend.DatabaseError:
            if force or self.ignore_errors in (direction, "all"):
                logger.exception("Ignored error in %r", self.step)
                return
            else:
                raise

    def rollback(self, backend, force=False):
        self.apply(backend, force, "rollback")


class MigrationStep(StepBase):
    """
    Model a single migration.

    Each migration step comprises apply and rollback steps of up and down SQL
    statements.
    """

    def __init__(self, id, apply, rollback):

        self.id = id
        self._rollback = rollback
        self._apply = apply

    def _execute(self, cursor, stmt, out=None):
        """
        Execute the given statement. If rows are returned, output these in a
        tabulated format.
        """
        if out is None:
            out = sys.stdout
        if isinstance(stmt, str):
            logger.debug(" - executing %r", stmt.encode("ascii", "replace"))
        else:
            logger.debug(" - executing %r", stmt)
        cursor.execute(stmt)
        if cursor.description:
            result = [
                [str(value) for value in row] for row in cursor.fetchall()
            ]
            column_names = [desc[0] for desc in cursor.description]
            column_sizes = [len(c) for c in column_names]

            for row in result:
                for ix, value in enumerate(row):
                    if len(value) > column_sizes[ix]:
                        column_sizes[ix] = len(value)
            format = "|".join(" %%- %ds " % size for size in column_sizes)
            format += "\n"
            out.write(format % tuple(column_names))
            out.write(
                "+".join("-" * (size + 2) for size in column_sizes) + "\n"
            )
            for row in result:
                out.write(format % tuple(row))
            out.write(plural(len(result), "(%d row)", "(%d rows)") + "\n")

    def apply(self, backend, force=False):
        """
        Apply the step.

        :param force: If true, errors will be logged but not be re-raised
        """
        logger.info(" - applying step %d", self.id)
        if not self._apply:
            return
        if isinstance(self._apply, str):
            cursor = backend.cursor()
            try:
                self._execute(cursor, self._apply)
            finally:
                cursor.close()
        else:
            self._apply(backend.connection)

    def rollback(self, backend, force=False):
        """
        Rollback the step.
        """
        logger.info(" - rolling back step %d", self.id)
        if self._rollback is None:
            return
        if isinstance(self._rollback, str):
            cursor = backend.cursor()
            try:
                self._execute(cursor, self._rollback)
            finally:
                cursor.close()
        else:
            self._rollback(backend.connection)


class StepGroup(MigrationStep):
    """
    Multiple steps aggregated together
    """

    def __init__(self, steps):
        self.steps = steps

    def __repr__(self):
        return "{}({!r})".format(self.__class__.__name__, self.steps)

    def apply(self, backend, force=False):
        for item in self.steps:
            item.apply(backend, force)

    def rollback(self, backend, force=False):
        for item in reversed(self.steps):
            item.rollback(backend, force)


def _expand_sources(sources) -> Iterable[Tuple[str, List[str]]]:
    package_match = re.compile(r"^package:([^\s\/:]+):(.*)$").match
    for source in sources:
        mo = package_match(source)
        if mo:
            package_name = mo.group(1)
            resource_dir = mo.group(2)
            paths = [
                pkg_resources.resource_filename(
                    package_name, "{}/{}".format(resource_dir, f)
                )
                for f in sorted(
                    pkg_resources.resource_listdir(package_name, resource_dir)
                )
                if _is_migration_file(f)
            ]
            yield (source, paths)
        else:
            for directory in glob(source):
                paths = [
                    os.path.join(directory, path)
                    for path in sorted(os.listdir(directory))
                    if _is_migration_file(path)
                ]
                yield (directory, paths)


def read_migrations(*sources):
    """
    Return a ``MigrationList`` containing all migrations from ``sources``.
    """
    migrations = OrderedDict()  # type: Dict[str, MigrationList]

    for source, paths in _expand_sources(sources):
        for path in paths:
            if path.endswith(".rollback.sql"):
                continue
            filename = os.path.splitext(os.path.basename(path))[0]

            migration_class = Migration
            if filename.startswith("post-apply"):
                migration_class = PostApplyHookMigration

            migration = migration_class(
                os.path.splitext(os.path.basename(path))[0],
                path,
                source_dir=source,
            )
            ml = migrations.setdefault(source, MigrationList())
            if migration_class is PostApplyHookMigration:
                ml.post_apply.append(migration)
            else:
                ml.append(migration)
    merged_migrations = MigrationList(
        chain(*migrations.values()),
        chain(*(m.post_apply for m in migrations.values())),
    )
    return merged_migrations


class MigrationList(abc.MutableSequence):
    """
    A list of database migrations.
    """

    def __init__(self, items=None, post_apply=None):
        self.items = list(items) if items else []
        self.post_apply = list(post_apply) if post_apply else []
        self.keys = set(item.id for item in self.items)
        self.check_conflicts()

    def __repr__(self):
        return "{}({})".format(self.__class__.__name__, repr(self.items))

    def check_conflicts(self):
        c = Counter()  # type: Dict[str, int]
        for item in self:
            c[item.id] += 1
            if c[item.id] > 1:
                raise exceptions.MigrationConflict(item.id)

    def __getitem__(self, n):
        if isinstance(n, slice):
            return self.__class__(self.items.__getitem__(n))
        return self.items.__getitem__(n)

    def __setitem__(self, n, ob):
        removing = self.items[n]
        if not isinstance(removing, list):
            remove_ids = set([item.id for item in removing])
            new_ids = {ob.id}
        else:
            remove_ids = set(item.id for item in removing)
            new_ids = {item.id for item in ob}

        for id in new_ids:
            if id in self.keys and id not in remove_ids:
                raise exceptions.MigrationConflict(id)

        self.keys.difference_update(removing)
        self.keys.update(new_ids)
        return self.items.__setitem__(n, ob)

    def __len__(self):
        return len(self.items)

    def __delitem__(self, i):
        self.keys.remove(self.items[i].id)
        self.items.__delitem__(i)

    def insert(self, i, x):
        if x.id in self.keys:
            raise exceptions.MigrationConflict(x.id)
        self.keys.add(x.id)
        return self.items.insert(i, x)

    def __add__(self, other):
        ob = copy(self)
        ob.extend(other)
        return ob

    def filter(self, predicate):
        return self.__class__(
            [m for m in self if predicate(m)], self.post_apply
        )

    def replace(self, newmigrations):
        return self.__class__(newmigrations, self.post_apply)


class StepCollector(object):
    """
    Provide the ``step`` and ``transaction`` functions used in migration
    scripts.

    Each call to step/transaction updates the StepCollector's ``steps`` list.
    """

    def __init__(self, migration):
        self.migration = migration
        self.steps = OrderedDict()
        self.step_id = count(0)

    def add_step(self, apply, rollback=None, ignore_errors=None):
        """
        Wrap the given apply and rollback code in a transaction, and add it
        to the list of steps.
        Return the transaction-wrapped step.
        """

        def do_add(use_transactions):
            wrapper = (
                TransactionWrapper if use_transactions else Transactionless
            )
            t = MigrationStep(
                next(self.step_id), apply, rollback
            )  # type: StepBase
            t = wrapper(t, ignore_errors)
            return t

        self.steps[do_add] = 1
        return do_add

    def add_step_group(self, *args, **kwargs):
        """
        Create a ``StepGroup`` group of steps.
        """
        if "steps" in kwargs:
            if args:
                raise ValueError(
                    "steps cannot be called with both keyword "
                    "and positional 'steps' argument"
                )

            steps = kwargs["steps"]
        else:
            steps = list(
                chain(
                    *(s if isinstance(s, abc.Iterable) else [s] for s in args)
                )
            )
        for s in steps:
            del self.steps[s]

        def do_add(use_transactions):
            ignore_errors = kwargs.pop("ignore_errors", None)
            wrapper = (
                TransactionWrapper if use_transactions else Transactionless
            )

            group = StepGroup(
                [create_step(use_transactions) for create_step in steps]
            )
            return wrapper(group, ignore_errors)

        self.steps[do_add] = 1
        return do_add

    def create_steps(self, use_transactions):
        return [create_step(use_transactions) for create_step in self.steps]


def _get_collector(depth=2):
    for stackframe in reversed(inspect.stack()):
        path = stackframe.frame.f_code.co_filename
        if path in _collectors:
            return _collectors[path]
    raise AssertionError(
        "Excected to be called in the context of a migration module import"
    )


def step(*args, **kwargs):
    return _get_collector().add_step(*args, **kwargs)


def group(*args, **kwargs):
    return _get_collector().add_step_group(*args, **kwargs)


#: Alias for compatibility purposes.
#: This no longer affects transaction handling.
transaction = group


def ancestors(migration, population):
    """
    Return the dependencies for ``migration`` from ``population``.

    :param migration: a :class:`~yoyo.migrations.Migration` object
    :param population: a collection of migrations
    """
    to_process = set()
    for m in migration.depends:
        to_process.add(m)

    deps = set()
    while to_process:
        m = to_process.pop()
        deps.add(m)
        for d in m.depends:
            if d in deps:
                continue
            deps.add(d)
            to_process.add(d)
    return deps


def descendants(migration, population):
    """
    Return all descendants of ``migration`` from ``population``.

    :param migration: a :class:`~yoyo.migrations.Migration` object
    :param population: a collection of migrations
    """
    population = set(population)
    descendants = {migration}
    while True:
        found = False
        for m in population - descendants:
            if set(m.depends) & descendants:
                descendants.add(m)
                found = True
        if not found:
            break
    descendants.remove(migration)
    return descendants


def heads(migration_list):
    """
    Return the set of migrations that have no child dependencies
    """
    heads = set(migration_list)
    for m in migration_list:
        heads -= m.depends
    return heads


def topological_sort(migration_list: MigrationList) -> Iterable[Migration]:

    # Make a copy of migration_list. It's probably an iterator.
    migration_list = list(migration_list)

    # Track graph edges in two parallel data structures.
    # Use OrderedDict so that we can traverse edges in order
    # and keep the sort stable
    forward_edges = defaultdict(
        OrderedDict
    )  # type: Dict[Migration, Dict[Migration, int]]
    backward_edges = defaultdict(
        OrderedDict
    )  # type: Dict[Migration, Dict[Migration, int]]

    def sort_by_stability_order(
        items, ordering={m: index for index, m in enumerate(migration_list)}
    ):
        return sorted(
            (item for item in items if item in ordering), key=ordering.get
        )

    for m in migration_list:
        for n in sort_by_stability_order(m.depends):
            forward_edges[n][m] = 1
            backward_edges[m][n] = 1

    def check_cycles(item):
        stack = [(item, [])]
        while stack:
            n, path = stack.pop()
            if n in path:
                raise exceptions.BadMigration(
                    "Circular dependencies among these migrations {}".format(
                        ", ".join(m.id for m in path + [n])
                    )
                )
            stack.extend((f, path + [n]) for f in forward_edges[n])

    seen = set()
    for item in migration_list:

        if item in seen:
            continue

        check_cycles(item)

        # if item is in a dedepency graph, go back to the root node
        while backward_edges[item]:
            item = next(iter(backward_edges[item]))

        # is item at the start of a dependency graph?
        if forward_edges[item]:
            stack = [item]
            while stack:
                m = stack.pop()
                yield m
                seen.add(m)
                for child in list(reversed(forward_edges[m])):
                    if all(
                        dependency in seen
                        for dependency in backward_edges[child]
                    ):
                        stack.append(child)
        else:
            yield item
            seen.add(item)
