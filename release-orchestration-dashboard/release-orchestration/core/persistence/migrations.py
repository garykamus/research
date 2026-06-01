"""
Ordered list of migrations. Each entry is (version: int, fn: Callable[[conn], None]).
Add new migrations at the end — never reorder existing entries.
"""
from __future__ import annotations

import sqlite3
from typing import Callable

from migrations.initial_schema import up as migration_001_up
from migrations.migration_002 import up as migration_002_up

MIGRATIONS: list[tuple[int, Callable[[sqlite3.Connection], None]]] = [
    (1, migration_001_up),
    (2, migration_002_up),
]
