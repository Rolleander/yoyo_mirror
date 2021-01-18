Yoyo database migrations
########################

`Source repository and issue tracker <https://sr.ht/~olly/yoyo>`_

Yoyo is a database schema migration tool. Migrations are written as
SQL files or Python scripts that define a list of migration steps.
They can be as simple as this:

.. code:: python

   # file: migrations/0001.create-foo.py
   from yoyo import step
   steps = [
      step(
          "CREATE TABLE foo (id INT, bar VARCHAR(20), PRIMARY KEY (id))",
          "DROP TABLE foo"
      )
   ]


Installation
==================

Install yoyo-migrations using from the PyPI, for example:

.. code:: shell

   pip install yoyo-migrations



Command line usage
==================

Start a new migration:

.. code:: shell

  yoyo new ./migrations -m "Add column to foo"

Apply migrations from directory ``migrations`` to a PostgreSQL database:

.. code:: shell

   yoyo apply --database postgresql://scott:tiger@localhost/db ./migrations

Rollback migrations previously applied to a MySQL database:

.. code:: shell

   yoyo rollback --database mysql://scott:tiger@localhost/database ./migrations

Reapply (ie rollback then apply again) migrations to a SQLite database at
location ``/home/sheila/important.db``:

.. code:: shell

    yoyo reapply --database sqlite:////home/sheila/important.db ./migrations

List available migrations:

.. code:: shell

    yoyo list --database sqlite:////home/sheila/important.db ./migrations


During development, the ``yoyo develop`` command can be used to apply any
unapplied migrations without further prompting:

.. code:: shell

    $ yoyo develop --database postgresql://localhost/mydb migrations
    Applying 3 migrations:
        [00000000_initial-schema]
        [00000001_add-table-foo]
        [00000002_add-table-bar]

If there are no migrations waiting to be applied the ``develop`` command will
instead roll back and reapply the last migration:

.. code:: shell

    $ yoyo develop --database postgresql://localhost/dev ./migrations
    Reapplying 1 migration:
        [00000002_add-table-bar]


Connecting to a database
------------------------

Database connections are specified using a URL. Examples:

.. code:: ini

  # SQLite: use 4 slashes for an absolute database path on unix like platforms
  database = sqlite:////home/user/mydb.sqlite

  # SQLite: use 3 slashes for a relative path
  database = sqlite:///mydb.sqlite

  # SQLite: absolute path on Windows.
  database = sqlite:///c:\home\user\mydb.sqlite

  # MySQL: Network database connection
  database = mysql://scott:tiger@localhost/mydatabase

  # MySQL: unix socket connection
  database = mysql://scott:tiger@/mydatabase?unix_socket=/tmp/mysql.sock

  # MySQL with the MySQLdb driver (instead of pymysql)
  database = mysql+mysqldb://scott:tiger@localhost/mydatabase

  # MySQL with SSL/TLS enabled
  database = mysql+mysqldb://scott:tiger@localhost/mydatabase?ssl=yes&sslca=/path/to/cert

  # PostgreSQL: database connection
  database = postgresql://scott:tiger@localhost/mydatabase

  # PostgreSQL: unix socket connection
  database = postgresql://scott:tiger@/mydatabase

  # PostgreSQL: changing the schema (via set search_path)
  database = postgresql://scott:tiger@/mydatabase?schema=some_schema

Password security
-----------------

You can specify your database username and password either as part of the
database connection string on the command line (exposing your database
password in the process list)
or in a configuration file where other users may be able to read it.

The ``-p`` or ``--prompt-password`` flag causes yoyo to prompt
for a password, helping prevent your credentials from being leaked.

Migration files
===============

The migrations directory contains a series of migration scripts. Each
migration script is a Python (``.py``) or SQL file (``.sql``).

The name of each file without the extension is used as the migration's unique
identifier. You may include migrations from multiple sources, but
identifiers are assumed to be globally unique, so it's wise to choose a unique
prefix for you project (eg ``<project-name>-0001-migration.sql``) or use the
``yoyo new`` command to generate a suitable filename.

Migrations scripts are run in dependency then filename order.

Each migration file is run in a single transaction where this is supported by
the database.

Yoyo creates tables in your target database to track which migrations have been
applied. By default these are:

- ``_yoyo_migration``
- ``_yoyo_log``
- ``_yoyo_version``
- ``yoyo_lock``

Migrations as Python scripts
-----------------------------

A migration script written in Python has the following structure:

.. code:: python

    #
    # file: migrations/0001_create_foo.py
    #
    from yoyo import step

    __depends__ = {"0000.initial-schema"}

    steps = [
      step(
          "CREATE TABLE foo (id INT, bar VARCHAR(20), PRIMARY KEY (id))",
          "DROP TABLE foo",
      ),
      step(
          "ALTER TABLE foo ADD COLUMN baz INT NOT NULL"
      )
    ]

The ``step`` function may take up to 3 arguments:

- ``apply``: an SQL query (or Python function, see below) to apply the migration step.
- ``rollback``: (optional) an SQL query (or Python function) to rollback the migration step.
- ``ignore_errors``: (optional, one of ``"apply"``, ``"rollback"`` or ``"all"``)
  causes yoyo to ignore database errors in either the apply stage, rollback stage or both.

Migration steps as Python functions
```````````````````````````````````

If SQL is not flexible enough, you may supply a Python function as
either or both of the ``apply`` or ``rollback`` arguments of ``step``.
Each function should take a database connection as its only argument:

.. code:: python

    #
    # file: migrations/0001_create_foo.py
    #
    from yoyo import step

    def apply_step(conn):
        cursor = conn.cursor()
        cursor.execute(
            # query to perform the migration
        )

    def rollback_step(conn):
        cursor = conn.cursor()
        cursor.execute(
            # query to undo the above
        )

    steps = [
      step(apply_step, rollback_step)
    ]

Dependencies
`````````````

Migrations may declare dependencies on other migrations via the
``__depends__`` attribute:

.. code:: python

    #
    # file: migrations/0002.modify-foo.py
    #
    __depends__ = {'0000.initial-schema', '0001.create-foo'}

    steps = [
      # migration steps
    ]


If you use the ``yoyo new`` command the ``_depends__`` attribute will be auto
populated for you.


Migrations as SQL scripts
-------------------------

An SQL migration script files should be named ``<migration-name>.sql`` and contain the one or more
SQL statements required to apply the migration.

.. code:: sql

    --
    -- file: migrations/0001.create-foo.sql
    --
    CREATE TABLE foo (id INT, bar VARCHAR(20), PRIMARY KEY (id));


SQL rollback steps should be saved in a separate file named
``<migration-name>.rollback.sql``:

.. code:: sql

    --
    -- file: migrations/0001.create-foo.rollback.sql
    --
    DROP TABLE foo;


Dependencies
`````````````

A structured SQL comment may be used to specify
dependencies as a space separated list:

.. code:: sql

    -- depends: 0000.initial-schema 0001.create-foo

    ALTER TABLE foo ADD baz INT;




Post-apply hook
---------------

It can be useful to have a script that is run after every successful migration.
For example you could use this to update database permissions or re-create
views.

To do this, create a special migration file called ``post-apply.py`` or
``post-apply.sql``. This file should have the same format as any other
migration file.


Configuration file
==================

Yoyo looks for a configuration file named ``yoyo.ini`` in the current working
directory or any ancestor directory.

If no configuration file is found ``yoyo`` will prompt you to
create one, populated from the current command line arguments.

Using a configuration file saves repeated typing,
avoids your database username and password showing in process listings
and lessens the risk of accidentally running migrations
against the wrong database (ie by re-running an earlier ``yoyo`` entry in
your command history when you have moved to a different directory).

If you do not want a config file to be loaded
add the ``--no-config-file`` parameter to the command line options.

The configuration file may contain the following options:

.. code:: ini

  [DEFAULT]

  # List of migration source directories. "%(here)s" is expanded to the
  # full path of the directory containing this ini file.
  sources = %(here)s/migrations %(here)s/lib/module/migrations

  # Target database
  database = postgresql://scott:tiger@localhost/mydb

  # Verbosity level. Goes from 0 (least verbose) to 3 (most verbose)
  verbosity = 3

  # Disable interactive features
  batch_mode = on

  # Editor to use when starting new migrations
  # "{}" is expanded to the filename of the new migration
  editor = /usr/local/bin/vim -f {}

  # An arbitrary command to run after a migration has been created
  # "{}" is expanded to the filename of the new migration
  post_create_command = hg add {}

  # A prefix to use for generated migration filenames
  prefix = myproject_


Config file inheritance and includes
------------------------------------


The special ``%inherit`` and ``%include`` directives allow config file inheritance and inclusion:


.. code:: ini

  #
  # file: yoyo-defaults.ini
  #
  [DEFAULT]
  sources = %(here)s/migrations

  #
  # file: yoyo.ini
  #
  [DEFAULT]

  ; Inherit settings from yoyo-defaults.ini
  ;
  ; Settings in inherited files are processed first and may be overridden by
  ; settings in this file
  %inherit = yoyo-defaults.ini

  ; Include settings from yoyo-local.ini
  ;
  ; Included files are processed after this file and may override the settings
  ; in this file
  %include = yoyo-local.ini


  ; Use '?' to avoid raising an error if the file does not exist
  %inherit = ?yoyo-defaults.ini

  database = sqlite:///%(here)s/mydb.sqlite

Substitutions and environment variables
---------------------------------------

The special variable ``%(here)s`` will be substituted with the directory name
of the config file.

Environment variables can be substituted with the same syntax, eg ``%(HOME)s``.

Substitutions are case-insensitive so for example ``%(HOME)s`` and ``%(home)s``
will both refer to the same variable.

Migration sources
-----------------

Yoyo reads migration scripts from the directories specified in the ``sources``
config option. Paths may include glob patterns, for example:

.. code:: ini

    [DEFAULT]
    sources =
        %(here)s/migrations
        %(here)s/src/*/migrations

You may also read migrations from installed python packages, by supplying a
path in the special form ``package:<package-name>:<path-to-migrations-dir>``,
for example:

.. code:: ini

    [DEFAULT]
    sources = package:myapplication:data/migrations


Transactions
============

Each migration runs in a separate transaction. Savepoints are used
to isolate steps within each migration.

If an error occurs during a step and the step has ``ignore_errors`` set,
then that individual step will be rolled back and
execution will pick up from the next step.
If ``ignore_errors`` is not set then the entire migration will be rolled back
and execution stopped.

Note that some databases (eg MySQL) do not support rollback on DDL statements
(eg ``CREATE ...`` and ``ALTER ...`` statements). For these databases
you may need to manually intervene to reset the database state
should errors occur in your migration.

Using ``group`` allows you to nest steps, giving you control of where
rollbacks happen. For example:

.. code:: python

    group([
      step("ALTER TABLE employees ADD tax_code TEXT"),
      step("CREATE INDEX tax_code_idx ON employees (tax_code)")
    ], ignore_errors='all')
    step("UPDATE employees SET tax_code='C' WHERE pay_grade < 4")
    step("UPDATE employees SET tax_code='B' WHERE pay_grade >= 6")
    step("UPDATE employees SET tax_code='A' WHERE pay_grade >= 8")

Disabling transactions
----------------------

You can disable transaction handling within a migration by setting
``__transactional__ = False``, eg:

.. code:: python

    __transactional__ = False

    step("CREATE DATABASE mydb", "DROP DATABASE mydb")

Or for SQL migrations:

.. code:: sql

    -- transactional: false

    CREATE DATABASE mydb

This feature is only tested against the PostgreSQL and SQLite backends.

PostgreSQL
``````````

In PostgreSQL it is an error to run certain statements inside a transaction
block. These include:

.. code:: sql

    CREATE DATABASE ...
    ALTER TYPE ... ADD VALUE

Using ``__transactional__ = False`` allows you to run these within a migration

SQLite
```````

In SQLite, the default transactional behavior may prevent other tools from
accessing the database for the duration of the migration. Using
``__transactional__ = False`` allows you to work around this limitation.


Calling Yoyo from Python code
=============================

The following example shows how to apply migrations from inside python code:

.. code:: python

    from yoyo import read_migrations
    from yoyo import get_backend

    backend = get_backend('postgres://myuser@localhost/mydatabase')
    migrations = read_migrations('path/to/migrations')

    with backend.lock():

        # Apply any outstanding migrations
        backend.apply_migrations(backend.to_apply(migrations))

        # Rollback all migrations
        backend.rollback_migrations(backend.to_rollback(migrations))

.. :vim:sw=4:et

.. toctree::
   :maxdepth: 2
   :caption: Contents:

Contributing
=============

Report an issue
----------------

Use the yoyo-migrations `issue tracker
<https://todo.sr.ht/~olly/yoyo>`_ to report issues.


There is also a `mailing list <https://lists.sr.ht/~olly/yoyo>`_ where you can
post questions or suggestions.


Pull requests
-------------

Yoyo-migrations is developed on sourcehut and uses a mailing list to review
commits for inclusion into the project.

To send commits to the mailing list:

1. Clone the repository: ``hg clone https://hg.sr.ht/~olly/yoyo``
2. Take care to commit your work in logically separate changes. Use ``hg commit -i`` to commit your work in logically separate changes. Make sure each commit has a meaningful message.
3. When you are ready to send your commits, use ``hg config --edit`` to add the
   following lines to your user Mercurial configuration file:

  .. code:: ini

     [extensions]
     patchbomb =

     [email]
     from = Your Name <you@example.org>
     method = smtp

     [smtp]
     host = mail.example.org
     port = 587
     tls = smtps
     username = you@example.org

  Then use ``hg config --local`` to add the following lines to the repository configuration file:

  .. code:: ini

     [email]
     to = <~olly/yoyo@lists.sr.ht>

4. Run ``hg mail -o`` to send your commits by email. This command will send all your commits; if you want to send just a subset, refer to the `hg email docs <https://www.mercurial-scm.org/doc/hg.1.html#email>`_.


For more detailed instructions, see here: https://man.sr.ht/hg.sr.ht/email.md


Mailing list
------------

The mailing list archives can be found here: https://lists.sr.ht/~olly/yoyo.




Changelog
=========

.. include:: ../CHANGELOG.rst
