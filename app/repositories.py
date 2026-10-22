"""PostgreSQL implementation of the tenant rules M2 proved with the in-memory store.

`SqlTenancy.scope(tenant_id)` is the only way in. Every read, write and delete goes
through a session whose statements carry `tenant_id == scope.tenant_id`, and a row that
belongs to another tenant is reported as `RecordNotFound` so its existence does not leak.

The interface is the same as `app.tenancy.TenantScope`, so a caller cannot tell which
store it is talking to — which is what lets the isolation tests survive the swap.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Iterator, Sequence

from sqlalchemy import func, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.db import make_session_factory
from app.models import (
    Base,
    MistakeTag,
    PerformanceMetric,
    RecoveryReport,
    Trade,
    TradingAccount,
    User,
)
from app.tenancy import RecordNotFound

#: docs/DATA_MODEL.md name -> table, for `counts()` and the schema test.
MODELS: dict[str, type[Base]] = {
    "User": User,
    "TradingAccount": TradingAccount,
    "Trade": Trade,
    "MistakeTag": MistakeTag,
    "PerformanceMetric": PerformanceMetric,
    "RecoveryReport": RecoveryReport,
}


class SqlTenancy:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine
        self._factory = make_session_factory(engine)

    @contextmanager
    def session(self) -> Iterator[Session]:
        session = self._factory()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def scope(self, tenant_id: str) -> "SqlScope":
        if not tenant_id:
            raise ValueError("a tenant scope needs a tenant id")
        return SqlScope(self._factory, tenant_id)


class SqlScope:
    """One tenant's view of the database."""

    def __init__(self, factory, tenant_id: str) -> None:
        self._factory = factory
        self.tenant_id = tenant_id

    @contextmanager
    def session(self) -> Iterator[Session]:
        session = self._factory()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    # -- reads -----------------------------------------------------------------

    def get(self, model: type[Base], row_id: str) -> Base:
        with self.session() as session:
            row = session.scalars(
                select(model).where(
                    model.id == row_id, model.tenant_id == self.tenant_id
                )
            ).first()
            if row is None:
                raise RecordNotFound(model.__tablename__, row_id)
            return row

    def list(
        self, model: type[Base], *, order_by: Any | None = None
    ) -> Sequence[Base]:
        with self.session() as session:
            statement = select(model).where(model.tenant_id == self.tenant_id)
            if order_by is not None:
                statement = statement.order_by(order_by)
            return list(session.scalars(statement).all())

    def counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        with self.session() as session:
            for name, model in MODELS.items():
                counts[name] = int(
                    session.execute(
                        select(func.count())
                        .select_from(model)
                        .where(model.tenant_id == self.tenant_id)
                    ).scalar_one()
                )
        return counts

    # -- writes ----------------------------------------------------------------

    def add(self, model: type[Base], **fields: Any) -> Base:
        fields.pop("tenant_id", None)  # the scope owns the tenant, never the caller
        with self.session() as session:
            row = model(**fields, tenant_id=self.tenant_id)
            session.add(row)
            session.flush()
            session.refresh(row)
            session.expunge(row)
            return row

    def update(self, model: type[Base], row_id: str, **fields: Any) -> Base:
        fields.pop("tenant_id", None)
        fields.pop("id", None)
        with self.session() as session:
            row = session.scalars(
                select(model).where(
                    model.id == row_id, model.tenant_id == self.tenant_id
                )
            ).first()
            if row is None:
                raise RecordNotFound(model.__tablename__, row_id)
            for key, value in fields.items():
                setattr(row, key, value)
            session.flush()
            session.refresh(row)
            session.expunge(row)
            return row

    def delete(self, model: type[Base], row_id: str) -> None:
        with self.session() as session:
            row = session.scalars(
                select(model).where(
                    model.id == row_id, model.tenant_id == self.tenant_id
                )
            ).first()
            if row is None:
                raise RecordNotFound(model.__tablename__, row_id)
            session.delete(row)
