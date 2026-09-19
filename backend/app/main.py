from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import inspect, text

from app.api.router import api_router
from app.config import settings
from app.database import Base, SessionLocal, engine
from app.services.seed import seed_if_empty


def _backfill_columns() -> None:
    """Lightweight additive migration for databases created before family rows.

    create_all only builds missing tables, so new columns on existing tables are
    added explicitly. Kept dialect-agnostic via the inspector.
    """
    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())
    with engine.begin() as conn:
        if "halls" in existing_tables:
            cols = {c["name"] for c in inspector.get_columns("halls")}
            if "family_rows" not in cols:
                conn.execute(text("ALTER TABLE halls ADD COLUMN family_rows VARCHAR(80) DEFAULT ''"))
        if "seat_holds" in existing_tables:
            cols = {c["name"] for c in inspector.get_columns("seat_holds")}
            if "with_children" not in cols:
                bool_default = "0" if engine.dialect.name == "sqlite" else "FALSE"
                conn.execute(
                    text(
                        f"ALTER TABLE seat_holds ADD COLUMN with_children BOOLEAN DEFAULT {bool_default}"
                    )
                )


@asynccontextmanager
async def lifespan(_app: FastAPI):
    Base.metadata.create_all(bind=engine)
    _backfill_columns()
    if settings.seed_on_empty:
        db = SessionLocal()
        try:
            seed_if_empty(db)
        finally:
            db.close()
    yield


app = FastAPI(title="SeatBond", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(api_router, prefix="/api")
