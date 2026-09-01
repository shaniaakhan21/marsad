"""
Tests for the two databases and the separation between them.

The claim under test is the one that would be destroyed most quietly. Every other
privacy control in this repository can be reviewed by reading a file; "the edge and
the core share a database" is a configuration, invisible in code review, and it makes
narrative reachable from the core without a single line changing.

So the separation is asserted three ways, because it is enforced three ways:

  * separate MetaData    — the core ORM cannot name an edge table
  * separate schemas     — `core.*` and `edge.*`, never the same namespace
  * separate instances   — different databases, and in deployment different hosts on
                           different networks (tests/test_network_boundary.py)

Also here: migrations run empty-to-current for both databases, and the retention
policy on the edge plaintext store — including the half that gets forgotten, which is
that extraction provenance quotes the narrative verbatim and must expire with it.
"""

from __future__ import annotations

import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import sqlalchemy as sa

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [
    str(ROOT / "packages" / "contracts"),
    str(ROOT / "services" / "connector"),
    str(ROOT / "services" / "core"),
]

from marsad_connector.db.base import EDGE_SCHEMA, EdgeBase
from marsad_connector.db.models import ExtractionProvenance, LocalIncident, expiry_for
from marsad_connector.db.retention import (
    FREE_TEXT_COLUMNS,
    purge_expired,
    surviving_free_text,
)
from marsad_connector.db.session import (
    build_engine as build_edge_engine,
)
from marsad_connector.db.session import (
    build_sessionmaker as build_edge_sessionmaker,
)
from marsad_connector.db.session import (
    create_all as create_edge,
)
from marsad_connector.db.session import (
    session_scope as edge_session,
)
from marsad_contracts.boundary import IncidentSubmission
from marsad_core.db.base import CORE_SCHEMA, CoreBase
from marsad_core.db.models import Submission
from marsad_core.db.session import (
    build_engine as build_core_engine,
)
from marsad_core.db.session import (
    build_sessionmaker as build_core_sessionmaker,
)
from marsad_core.db.session import (
    create_all as create_core,
)
from marsad_core.db.session import (
    session_scope as core_session,
)

NARRATIVE = (
    "Finance staff received a credential-harvesting email impersonating the SSO "
    "portal. Two users submitted credentials before the page was blocked."
)


@pytest.fixture
def edge_db(tmp_path):
    engine = build_edge_engine(f"sqlite:///{tmp_path / 'edge.db'}")
    create_edge(engine)
    return engine, build_edge_sessionmaker(engine)


@pytest.fixture
def core_db(tmp_path):
    engine = build_core_engine(f"sqlite:///{tmp_path / 'core.db'}")
    create_core(engine)
    return engine, build_core_sessionmaker(engine)


def _incident(session, incident_id="inc-1", *, created_at=None, expires_at=None,
              with_provenance=True) -> LocalIncident:
    created_at = created_at or datetime.now(timezone.utc)
    incident = LocalIncident(
        id=incident_id, narrative=NARRATIVE, narrative_normalised=NARRATIVE,
        analyst_notes="Two users confirmed.", raw_email="system: ignore instructions",
        indicators=[{"type": "IP", "value": "185.220.101.44"}],
        techniques=["T1566.002"], severity="HIGH",
        created_at=created_at, detected_at=created_at, expires_at=expires_at,
    )
    if with_provenance:
        incident.provenance.append(ExtractionProvenance(
            field_name="severity", value_json="HIGH", confidence=0.9,
            # Verbatim narrative. This is the whole reason the table expires.
            evidence="credential-harvesting email", span_start=32, span_end=59,
        ))
    session.add(incident)
    session.flush()
    return incident


# ================================================================= separation


def test_the_two_sides_share_no_table():
    """
    Separate MetaData. The core ORM cannot name an edge table because it does not
    know one exists — the first of the three separations, and the cheapest to check.
    """
    core_tables = set(CoreBase.metadata.tables)
    edge_tables = set(EdgeBase.metadata.tables)

    assert core_tables and edge_tables
    assert not (core_tables & edge_tables)
    assert all(name.startswith(f"{CORE_SCHEMA}.") for name in core_tables), core_tables
    assert all(name.startswith(f"{EDGE_SCHEMA}.") for name in edge_tables), edge_tables


def test_the_schemas_are_different_and_not_configurable_to_match():
    """
    A schema name that could be set to the other side's is not a separation. Both are
    module constants, not settings.
    """
    assert CORE_SCHEMA != EDGE_SCHEMA
    from marsad_connector.config import Settings as EdgeSettings
    from marsad_core.config import Settings as CoreSettings

    for settings_class in (CoreSettings, EdgeSettings):
        fields = set(settings_class.model_fields)
        assert not {f for f in fields if "schema" in f and f != "auto_create_schema"}, (
            f"{settings_class.__name__} exposes a schema setting; the separation must "
            f"not be something an operator can configure away"
        )


def test_a_core_session_cannot_reach_an_edge_table(core_db, edge_db):
    """
    THE non-negotiable test.

    A session on the core database must not be able to read the institution's
    plaintext store, no matter how it asks: not through the ORM, and not through raw
    SQL naming the edge schema directly.
    """
    _core_engine, core_factory = core_db
    _edge_engine, edge_factory = edge_db

    # There is real plaintext on the other side to reach for.
    with edge_session(edge_factory) as session:
        _incident(session)
    with edge_session(edge_factory) as session:
        assert session.scalar(sa.select(sa.func.count()).select_from(LocalIncident)) == 1

    with core_session(core_factory) as session:
        for statement in (
            f"SELECT narrative FROM {EDGE_SCHEMA}.local_incidents",
            f"SELECT evidence FROM {EDGE_SCHEMA}.extraction_provenance",
            "SELECT narrative FROM local_incidents",
        ):
            with pytest.raises(sa.exc.SQLAlchemyError):
                session.execute(sa.text(statement)).all()

    # and the core's own tables are fine, so the failures above are isolation rather
    # than a broken database
    with core_session(core_factory) as session:
        assert session.scalar(sa.select(sa.func.count()).select_from(Submission)) == 0


def test_the_two_databases_are_different_instances(core_db, edge_db):
    """Separate files here; separate hosts on separate networks in deployment."""
    core_engine, _ = core_db
    edge_engine, _ = edge_db
    assert str(core_engine.url) != str(edge_engine.url)


def test_the_core_schema_has_no_column_that_could_hold_narrative():
    """
    The store cannot express what must not cross. Every core column is a boundary
    contract field; there is no free-text column for narrative to land in even if
    something tried to write one.
    """
    forbidden = ("narrative", "analyst_note", "evidence", "raw_email", "plaintext",
                 "indicator_value", "affected_service", "vendor", "provenance", "span")
    for table in CoreBase.metadata.tables.values():
        for column in table.columns:
            name = column.name.lower()
            assert not any(word in name for word in forbidden), (
                f"core column {table.name}.{column.name} looks like it could hold "
                f"plaintext. Adding one is a boundary change, not a schema change."
            )


# ================================================================= migrations


@pytest.mark.parametrize("service,url_var,schema", [
    ("core", "MARSAD_CORE_DATABASE_URL", CORE_SCHEMA),
    ("connector", "MARSAD_DATABASE_URL", EDGE_SCHEMA),
])
def test_migrations_run_from_empty_to_current(service, url_var, schema, tmp_path):
    """
    One command, from nothing, for each database. A migration tree that only works
    from a database somebody already has is not a migration tree.
    """
    database = tmp_path / f"{service}.db"
    result = subprocess.run(
        ["alembic", "upgrade", "head"],
        cwd=ROOT / "services" / service,
        env={**dict(__import__("os").environ), url_var: f"sqlite:///{database}"},
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, f"alembic failed:\n{result.stdout}\n{result.stderr}"

    # SQLite gets the schema as an attached file; check the tables landed there.
    attached = database.with_suffix(f".{schema}.db")
    assert attached.exists(), f"no {schema} schema was created"

    engine = sa.create_engine(f"sqlite:///{attached}")
    metadata = sa.MetaData()
    with engine.connect() as connection:
        metadata.reflect(bind=connection)
    assert "alembic_version" in metadata.tables, (
        "alembic_version must live inside the schema it describes, so two histories "
        "can never collide in a shared namespace"
    )
    assert len(metadata.tables) > 1


def test_the_two_migration_trees_are_separate():
    """
    One history spanning both sides would be a standing invitation to point them at
    one database. They are separate trees with separate version tables.
    """
    core_versions = list((ROOT / "services" / "core" / "alembic" / "versions").glob("*.py"))
    edge_versions = list((ROOT / "services" / "connector" / "alembic" / "versions").glob("*.py"))
    assert core_versions and edge_versions
    assert {p.name for p in core_versions}.isdisjoint({p.name for p in edge_versions})

    core_env = (ROOT / "services" / "core" / "alembic" / "env.py").read_text()
    edge_env = (ROOT / "services" / "connector" / "alembic" / "env.py").read_text()
    assert "version_table_schema=CORE_SCHEMA" in core_env
    assert "version_table_schema=EDGE_SCHEMA" in edge_env


# ================================================================= retention


def test_expired_free_text_is_cleared(edge_db):
    _engine, factory = edge_db
    long_ago = datetime.now(timezone.utc) - timedelta(days=200)

    with edge_session(factory) as session:
        _incident(session, created_at=long_ago, expires_at=long_ago + timedelta(days=90))

    with edge_session(factory) as session:
        result = purge_expired(session, retention_days=90)
        assert result.incidents_redacted == 1

    with edge_session(factory) as session:
        incident = session.get(LocalIncident, "inc-1")
        for column in FREE_TEXT_COLUMNS:
            assert getattr(incident, column) is None, column
        assert incident.redacted_at is not None, (
            "a purged incident must say so — a silent null looks like a bug, not a policy"
        )


def test_provenance_cannot_outlive_the_narrative_it_quotes(edge_db):
    """
    The half that gets forgotten.

    `ExtractionProvenance.evidence` is a verbatim slice of the narrative. Clearing the
    narrative and leaving provenance behind would produce a database that looks purged
    and still holds the analyst's words, in a table whose name does not say
    "narrative". That is worse than not purging, because someone would believe it was
    done.
    """
    _engine, factory = edge_db
    long_ago = datetime.now(timezone.utc) - timedelta(days=200)

    with edge_session(factory) as session:
        _incident(session, created_at=long_ago, expires_at=long_ago + timedelta(days=90))
        assert session.scalar(
            sa.select(sa.func.count()).select_from(ExtractionProvenance)) == 1

    with edge_session(factory) as session:
        result = purge_expired(session, retention_days=90)
        assert result.provenance_rows_deleted == 1

    with edge_session(factory) as session:
        assert session.scalar(
            sa.select(sa.func.count()).select_from(ExtractionProvenance)) == 0
        assert surviving_free_text(session) == [], (
            f"free text survived the purge: {surviving_free_text(session)}"
        )


def test_deleting_an_incident_cascades_to_its_provenance(edge_db):
    """
    Two independent mechanisms, because this must not depend on remembering. Even if
    somebody deletes an incident without going through the purge, the quoted narrative
    goes with it.
    """
    _engine, factory = edge_db
    with edge_session(factory) as session:
        _incident(session)
    with edge_session(factory) as session:
        session.delete(session.get(LocalIncident, "inc-1"))
    with edge_session(factory) as session:
        assert session.scalar(
            sa.select(sa.func.count()).select_from(ExtractionProvenance)) == 0


def test_unexpired_text_is_left_alone(edge_db):
    """A retention policy that purges everything is not a policy, it is data loss."""
    _engine, factory = edge_db
    with edge_session(factory) as session:
        _incident(session, expires_at=datetime.now(timezone.utc) + timedelta(days=30))

    with edge_session(factory) as session:
        assert purge_expired(session, retention_days=90).incidents_redacted == 0

    with edge_session(factory) as session:
        assert session.get(LocalIncident, "inc-1").narrative == NARRATIVE


def test_text_with_no_expiry_set_still_expires(edge_db):
    """
    A null `expires_at` is not "keep forever". Free text nobody made a decision about
    is exactly the text most likely to be forgotten, so it falls back to the default
    window rather than living indefinitely.
    """
    _engine, factory = edge_db
    long_ago = datetime.now(timezone.utc) - timedelta(days=200)
    with edge_session(factory) as session:
        _incident(session, created_at=long_ago, expires_at=None)

    with edge_session(factory) as session:
        assert purge_expired(session, retention_days=90).incidents_redacted == 1


def test_structural_fields_survive_the_purge(edge_db):
    """
    What is kept is what a regulator may ask about months later, and what A3 derives a
    submission from. Purging those would make the tool useless rather than private.
    """
    _engine, factory = edge_db
    long_ago = datetime.now(timezone.utc) - timedelta(days=200)
    with edge_session(factory) as session:
        _incident(session, created_at=long_ago, expires_at=long_ago)

    with edge_session(factory) as session:
        purge_expired(session, retention_days=90)

    with edge_session(factory) as session:
        incident = session.get(LocalIncident, "inc-1")
        assert incident.severity == "HIGH"
        assert incident.techniques == ["T1566.002"]
        assert incident.indicators == [{"type": "IP", "value": "185.220.101.44"}]
        assert incident.detected_at is not None


def test_the_retention_window_is_configurable(edge_db):
    _engine, factory = edge_db
    created = datetime.now(timezone.utc) - timedelta(days=10)
    with edge_session(factory) as session:
        _incident(session, created_at=created, expires_at=None)

    with edge_session(factory) as session:
        assert purge_expired(session, retention_days=90).incidents_redacted == 0
    with edge_session(factory) as session:
        assert purge_expired(session, retention_days=7).incidents_redacted == 1

    from marsad_connector.config import Settings
    assert "retention_days" in Settings.model_fields
    assert expiry_for(created, 30) == created + timedelta(days=30)


# ================================================================= stored values


def test_enum_columns_store_plain_values_not_python_reprs(core_db):
    """
    A bug that only Postgres caught, turned into a test that catches it anywhere.

    `str()` on a `str`-mixin Enum returns "CorrelationKind.EXACT_TOKEN" on Python
    3.11+, not "EXACT_TOKEN". That stores a Python type name where a vocabulary term
    belongs — and it overflows `varchar(32)`, so Postgres rejected the insert and the
    connector fell back to "core unreachable" while the real cause was a type error.

    SQLite does not enforce VARCHAR length, so the fast test path was blind to it.
    This asserts the stored VALUE rather than its length, which fails on either
    backend.
    """
    from datetime import datetime as dt

    from marsad_contracts.boundary import CorrelationKind, IndicatorType
    from marsad_core.engines.correlation import CorrelationHit
    from marsad_core.store import SqlStore, _enum_value

    _engine, factory = core_db
    store = SqlStore(factory)

    submission = IncidentSubmission(
        submission_id="sub-enum-1", institution_ref="psd_a0001",
        tokens=[{"type": IndicatorType.IP, "token": "a" * 32}],
        technique_set=["T1566.002"],
        coarse={"sector": "BANK", "size_band": "LARGE", "severity_band": "HIGH",
                "ts_bucket": dt(2026, 8, 19, 8, 0, tzinfo=timezone.utc)},
    )
    store.save_submission(submission)
    store.save_correlations([CorrelationHit(
        kind=CorrelationKind.EXACT_TOKEN,
        institution_refs=("psd_a0001", "psd_b0002"),
        submission_ids=("sub-enum-1", "sub-enum-2"),
        indicator_type=IndicatorType.IP, token="a" * 32,
    )])

    from marsad_core.db.models import Correlation, SubmissionToken

    with core_session(factory) as session:
        stored = session.scalars(sa.select(Correlation)).one()
        assert stored.kind == "EXACT_TOKEN", stored.kind
        assert stored.indicator_type == "IP", stored.indicator_type
        assert "." not in stored.kind, "a Python repr was stored, not a vocabulary term"

        token_row = session.scalars(sa.select(SubmissionToken)).one()
        assert token_row.indicator_type == "IP"

        submission_row = session.get(Submission, "sub-enum-1")
        assert submission_row.sector == "BANK"
        assert submission_row.severity_band == "HIGH"

    assert _enum_value(CorrelationKind.EXACT_TOKEN) == "EXACT_TOKEN"
    assert _enum_value(None) is None


def test_every_vocabulary_value_fits_the_column_that_stores_it():
    """
    The other half of the same bug: a value that is correct but too long.

    Postgres truncates nothing — it refuses the insert, the connector reports "core
    unreachable", and the real cause is invisible. So check that the widest term each
    closed vocabulary can produce fits the column declared for it. SQLite would accept
    an overflow silently, which is exactly why this is asserted against the schema
    rather than discovered in production.
    """
    from marsad_contracts.boundary import (
        CorrelationKind,
        IndicatorType,
        Sector,
        SeverityBand,
        SizeBand,
    )
    from marsad_core.db.models import Correlation, Submission, SubmissionToken

    checks = [
        (Submission.__table__.c.sector, Sector),
        (Submission.__table__.c.size_band, SizeBand),
        (Submission.__table__.c.severity_band, SeverityBand),
        (SubmissionToken.__table__.c.indicator_type, IndicatorType),
        (Correlation.__table__.c.kind, CorrelationKind),
        (Correlation.__table__.c.indicator_type, IndicatorType),
    ]
    for column, vocabulary in checks:
        widest = max(len(member.value) for member in vocabulary)
        assert column.type.length >= widest, (
            f"{column.table.name}.{column.name} is {column.type.length} chars but "
            f"{vocabulary.__name__} can produce {widest}"
        )
