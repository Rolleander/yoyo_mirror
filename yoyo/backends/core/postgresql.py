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

from contextlib import contextmanager

from yoyo.backends.base import DatabaseBackend


class PostgresqlBackend(DatabaseBackend):

    driver_module = "psycopg2"
    schema = None
    list_tables_sql = (
        "SELECT table_name FROM information_schema.tables "
        "WHERE table_schema = :schema"
    )

    def connect(self, dburi):
        kwargs = {"dbname": dburi.database}
        kwargs.update(dburi.args)
        if dburi.username is not None:
            kwargs["user"] = dburi.username
        if dburi.password is not None:
            kwargs["password"] = dburi.password
        if dburi.port is not None:
            kwargs["port"] = dburi.port
        if dburi.hostname is not None:
            kwargs["host"] = dburi.hostname
        self.schema = kwargs.pop("schema", None)
        return self.driver.connect(**kwargs)

    @contextmanager
    def disable_transactions(self):
        with super(PostgresqlBackend, self).disable_transactions():
            saved = self.connection.autocommit
            self.connection.autocommit = True
            yield
            self.connection.autocommit = saved

    def init_connection(self, connection):
        if self.schema:
            cursor = connection.cursor()
            cursor.execute("SET search_path TO {}".format(self.schema))

    def list_tables(self):
        current_schema = self.execute("SELECT current_schema").fetchone()[0]
        return super(PostgresqlBackend, self).list_tables(schema=current_schema)


class PostgresqlPsycopgBackend(PostgresqlBackend):
    """
    Like PostgresqlBackend, but using the newer Psycopg 3.
    """

    driver_module = "psycopg"
