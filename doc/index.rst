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


Installation and project setup
==============================

Install yoyo-migrations from PyPI:

.. code:: shell

   pip install yoyo-migrations


Initialize yoyo for your project, supplying a database connection string and migrations directory name, for example:

.. code:: shell

    yoyo init --database sqlite:///mydb.sqlite3 migrations

This will create a new, empty directory called ``migrations`` and install a
``yoyo.ini`` configuration file in the current directory. The configuration file
will contain any database credentials supplied on the command line. If you do
not wish this to happen, then omit the ``--database`` argument from the
command.

Create a new migration by running ``yoyo new``. By default, a Python format file is generated, use ``--sql`` if you prefer SQL format:

.. code:: shell

    yoyo new --sql

An editor will open with a template migration file.
Add a comment explaining what the migration does followed by the SQL commands,
for example:

.. code:: sql

   -- Create table foo
   -- depends:

   CREATE TABLE foo (
        a int
   );


Save and exit, and the new migration file will be created.
Check your migration has been created with ``yoyo list`` and apply it with
``yoyo apply``:

.. code:: shell

    $ yoyo list
    $ yoyo apply



Command line usage
==================

You can see the list of available commands by running:

.. command-output:: yoyo --help


You can check options for any command with ``yoyo <command> --help``

yoyo new
--------

Start a new migration. ``yoyo new`` will create a new migration file and opens it your configured editor.

By default a Python formation migration will be created. To use the simpler SQL format, specify ``--sql``.

.. code:: shell

  yoyo new -m "Add column to foo"
  yoyo new --sql

yoyo list
----------

List available migrations. Each migration will be prefixed with one of ``U``
(unapplied) or ``A`` (applied).

yoyo apply
----------

Apply migrations to the target database. By default this will prompt you for each unapplied migration. To turn off prompting use ``--batch`` or specify ``batch_mode = on`` in ``yoyo.ini``.


yoyo rollback
-------------

By default this will prompt you for each applied migration, starting with the most recently applied.

If you wish to rollback a single migration, specify the migration with the ``-r``/``--revision`` flag. Note that this will also cause any migrations that depend on the selected migration to be rolled back.


yoyo reapply
-------------

Reapply (ie rollback then apply again) migrations. As with `yoyo rollback`_, you can select a target migration with ``-r``/``--revision``


yoyo develop
------------

Apply any unapplied migrations without prompting.

If there are no unapplied migrations, rollback and reapply the most recent
migration. Use ``yoyo develop -n <n>`` to act on just the *n* most recently
applied migrations.

yoyo mark
---------

Mark one or more migrations as applied, without actually applying them.

yoyo unmark
-----------

Unmark one or more migrations as unapplied, without actually rolling them back.



Connecting to a database
========================

Database connections are specified using a URL, for example:

.. code:: shell

    yoyo list --database postgresql://scott:tiger@localhost/mydatabase

The protocol part of the URL (the part before ``://``) is used to specify the backend.
Yoyo provides the following core backends:

- ``postgresql`` (psycopg2_)
- ``postgresql+psycopg`` (psycopg3_)
- ``mysql`` (pymysql_)
- ``mysql+mysqldb`` (mysqlclient_)
- ``sqlite`` (sqlite3_)

And these backends have been contributed and are bundled with yoyo:

- ``odbc`` (pyodbc_)
- ``oracle`` (`cx_Oracle`_)
- ``snowflake`` (snowflake_)
- ``redshift`` (psycopg2_)

How other parts of the URL are interpreted depends on the underlying backend
and the DB-API driver used. The host part especially tends to be interpreted
differently by drivers. A few of the more important differences are listed below.

MySQL connections
-----------------

mysqlclient_ and pymysql_ have
different ways to interpret the ``host`` part of the connection URL:

- With mysqlclient_ (``mysql+mysqldb://``),
  setting the host to ``localhost`` or leaving it empty causes the
  driver to attempt a local unix socket connection.
- In pymysql_ (``mysql://``),
  the driver will attempt a tcp connection in both cases.
  Specify a unix socket connection
  with the ``unix_socket`` option (eg ``?unix_socket=/tmp/mysql.sock``)

To enable SSL, specify ``?ssl=1`` and the following options as required:

- ``sslca``
- ``sslcapath``
- ``sslcert``
- ``sslkey``
- ``sslcipher``

These options correspond to the ``ca``, ``capath``, ``cert``, ``key`` and ``cipher`` options used by `mysql_ssl_set <https://dev.mysql.com/doc/c-api/8.0/en/mysql-ssl-set.html>`_.

Example configurations:

.. code:: ini

  # MySQL: Network database connection
  database = mysql://scott:tiger@localhost/mydatabase

  # MySQL: unix socket connection
  database = mysql://scott:tiger@/mydatabase?unix_socket=/tmp/mysql.sock

  # MySQL with the MySQLdb driver (instead of pymysql)
  database = mysql+mysqldb://scott:tiger@localhost/mydatabase

  # MySQL with SSL/TLS enabled
  database = mysql+mysqldb://scott:tiger@localhost/mydatabase?ssl=yes&sslca=/path/to/cert

PostgreSQL connections
----------------------

The psycopg family of drivers will use a unix socket if the host is left empty
(or the value of ``PGHOST`` if this is set in your environment). Otherwise it will attempt a tcp connection to the specified host.

To force a unix socket connection leave the host part of the URL
empty and provide a ``host`` option that points to the directory containing the socket
(eg ``postgresql:///mydb?host=/path/to/socket/``).

The postgresql backends also allow a custom schema to be selected by specifying a ``schema`` option, eg ``postgresql://…/mydatabase?schema=myschema``.

Example configurations:

.. code:: ini

  database = postgresql://scott:tiger@localhost/mydatabase

  # unix socket connection
  database = postgresql://scott:tiger@/mydatabase

  # unix socket at a non-standard location and port number
  database = postgresql://scott:tiger@/mydatabase?host=/var/run/postgresql&port=5434

  # PostgreSQL with psycopg 3 driver
  database = postgresql+psycopg://scott:tiger@localhost/mydatabase

  # Changing the default schema
  database = postgresql://scott:tiger@/mydatabase?schema=some_schema

SQLite connections
------------------

The SQLite backend ignores everything in the connection URL except the database
name, which should be a filename, or the special value ``:memory:`` for an in-memory database.

3 slashes are required to specify a relative path::

    sqlite:///mydb.sqlite

and 4 for an absolute path on unix-like platforms::

    sqlite:////home/user/mydb.sqlite


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


If you use the ``yoyo new`` command the ``__depends__`` attribute will be auto
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

Disable transaction handling within a migration by setting
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

    backend = get_backend('postgresql://myuser@localhost/mydatabase')
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


Adding custom backends
======================

Backends are discovered using Python importlib.metadata entry points.

To add a custom backend, create a python package containing a subclass of
:class:`yoyo.backends.base.DatabaseBackend` and configure it
in the package metadata (typically in ``setup.cfg``), for example:

.. code:: ini

    [options.entry_points]

    yoyo.backends =
        mybackend = mypackage:MyBackend


Use the backend by specifying ``'mybackend'`` as the driver protocol::

  .. code:: sh

   yoyo apply --database my_backend://...


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
.. _mysqlclient: https://pypi.org/project/mysqlclient/
.. _pymysql: https://pypi.org/project/pymysql/
.. _psycopg2: https://pypi.org/project/psycopg2/
.. _psycopg3: https://pypi.org/project/psycopg/
.. _sqlite3: https://docs.python.org/3/library/sqlite3.html
.. _pyodbc: https://pypi.org/project/pyodbc/
.. _cx_Oracle: https://pypi.org/project/cx-Oracle/
.. _snowflake: https://pypi.org/project/snowflake-connector-python/
