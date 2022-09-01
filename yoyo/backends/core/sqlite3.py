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

from yoyo.backends.base import DatabaseBackend


class SQLiteBackend(DatabaseBackend):

    driver_module = "sqlite3"
    list_tables_sql = "SELECT name FROM sqlite_master WHERE type = 'table'"

    def connect(self, dburi):
        # Ensure that multiple connections share the same data
        # https://sqlite.org/sharedcache.html
        conn = self.driver.connect(
            f"file:{dburi.database}?cache=shared",
            uri=True,
            detect_types=self.driver.PARSE_DECLTYPES,
        )
        conn.isolation_level = None
        return conn
