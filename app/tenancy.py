"""Tenant-scoped records: the only way to read or write a row.

AGENTS.md: every database row carries the tenant id, and every query filters by it.
`TenantScope` is the enforcement point. It takes the tenant from the signed-in user, not
from the request, and it refuses to see, change or delete a row belonging to another
tenant — reported as "not found", so its existence does not leak either.

Storage is in memory for now: M3 brings PostgreSQL behind the same interface, and these
rules are what the SQL has to keep.
"""

from __future__ import annotations

import secrets
from threading import Lock
from typing import Any

#: Every table in docs/DATA_MODEL.md. The test suite checks this against the doc.
TABLES: tuple[str, ...] = (
    "User",
    "TradingAccount",
    "Trade",
    "MistakeTag",
    "PerformanceMetric",
    "RecoveryReport",
)

Row = dict[str, Any]


class RecordNotFound(LookupError):
    """No such row *in this workspace*. Deliberately does not distinguish the two cases."""

    def __init__(self, table: str, row_id: str) -> None:
        super().__init__(f"{table}: no record {row_id} in this workspace")
        self.table = table
        self.row_id = row_id


class TenancyStore:
    """Owns the rows. Reach it only through `scope(tenant_id)`."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._rows: dict[str, dict[str, Row]] = {table: {} for table in TABLES}

    def scope(self, tenant_id: str) -> "TenantScope":
        if not tenant_id:
            raise ValueError("a tenant scope needs a tenant id")
        return TenantScope(self, tenant_id)

    # -- used by TenantScope only ------------------------------------------------

    def _add(self, table: str, tenant_id: str, fields: Row) -> Row:
        self._check_table(table)
        with self._lock:
            row_id = fields.pop("id", None) or f"{table.lower()}_{secrets.token_hex(6)}"
            row = {**fields, "id": row_id, "tenant_id": tenant_id}
            self._rows[table][row_id] = row
            return dict(row)

    def _get(self, table: str, tenant_id: str, row_id: str) -> Row:
        self._check_table(table)
        with self._lock:
            row = self._rows[table].get(row_id)
            if row is None or row.get("tenant_id") != tenant_id:
                raise RecordNotFound(table, row_id)
            return dict(row)

    def _update(self, table: str, tenant_id: str, row_id: str, fields: Row) -> Row:
        self._check_table(table)
        with self._lock:
            row = self._rows[table].get(row_id)
            if row is None or row.get("tenant_id") != tenant_id:
                raise RecordNotFound(table, row_id)
            for key, value in fields.items():
                if key in {"id", "tenant_id"}:
                    continue  # identity and ownership are not editable
                row[key] = value
            return dict(row)

    def _delete(self, table: str, tenant_id: str, row_id: str) -> None:
        self._check_table(table)
        with self._lock:
            row = self._rows[table].get(row_id)
            if row is None or row.get("tenant_id") != tenant_id:
                raise RecordNotFound(table, row_id)
            del self._rows[table][row_id]

    def _list(self, table: str, tenant_id: str) -> list[Row]:
        self._check_table(table)
        with self._lock:
            return [
                dict(row)
                for row in self._rows[table].values()
                if row.get("tenant_id") == tenant_id
            ]

    def _counts(self, tenant_id: str) -> dict[str, int]:
        with self._lock:
            return {
                table: sum(1 for row in rows.values() if row.get("tenant_id") == tenant_id)
                for table, rows in self._rows.items()
            }

    @staticmethod
    def _check_table(table: str) -> None:
        if table not in TABLES:
            raise KeyError(f"{table} is not a table in docs/DATA_MODEL.md")


class TenantScope:
    """One tenant's view. Every method is filtered; there is no unfiltered escape hatch."""

    def __init__(self, store: TenancyStore, tenant_id: str) -> None:
        self._store = store
        self.tenant_id = tenant_id

    def add(self, table: str, **fields: Any) -> Row:
        return self._store._add(table, self.tenant_id, dict(fields))

    def get(self, table: str, row_id: str) -> Row:
        return self._store._get(table, self.tenant_id, row_id)

    def update(self, table: str, row_id: str, **fields: Any) -> Row:
        return self._store._update(table, self.tenant_id, row_id, dict(fields))

    def delete(self, table: str, row_id: str) -> None:
        self._store._delete(table, self.tenant_id, row_id)

    def list(self, table: str) -> list[Row]:  # noqa: A003 - the noun reads better here
        return self._store._list(table, self.tenant_id)

    def counts(self) -> dict[str, int]:
        return self._store._counts(self.tenant_id)
