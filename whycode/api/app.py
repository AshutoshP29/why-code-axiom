"""The WhyCode API for the screens: every path under /api, every call scoped to one repo.

    uv run uvicorn whycode.api.app:app --reload --port 8000

WHYCODE_GRAPH_TARGET picks the Neo4j database: "aura" (default, needs .env) or "test" (the
docker-compose container). The driver is made on the first request, so importing this module
needs no configuration.
"""

import os
from contextlib import asynccontextmanager
from datetime import date
from functools import lru_cache
from typing import Annotated

import psycopg
from fastapi import APIRouter, Depends, FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from neo4j.exceptions import AuthError, ServiceUnavailable, SessionExpired

from whycode.api import answers, lineage, reads
from whycode.api import models as m
from whycode.api.gaps import GapStore
from whycode.config import ConfigError
from whycode.graph.queries import Run, neo4j_runner
from whycode.ids import normalize_repo

TARGET_ENV = "WHYCODE_GRAPH_TARGET"
CORS_ORIGINS = ["http://localhost:5173", "http://127.0.0.1:5173"]
NOT_IMPLEMENTED = {"detail": "not implemented yet"}
TEST_POSTGRES_DSN = "postgresql://whycode:whycode_dev_only@127.0.0.1:5433/whycode"  # dev only


@lru_cache(maxsize=1)
def _graph():
    from whycode.graph.client import aura_target, local_test_target

    name = os.environ.get(TARGET_ENV, "aura").strip().lower()
    if name == "test":
        target = local_test_target()
    elif name == "aura":
        from whycode.config import get_settings

        target = aura_target(get_settings())
    else:
        raise ConfigError(f"{TARGET_ENV} must be 'aura' or 'test'")
    return target.driver(), target.database


def get_run() -> Run:
    driver, database = _graph()
    return neo4j_runner(driver, database)


@lru_cache(maxsize=1)
def _gap_store() -> GapStore:
    if os.environ.get(TARGET_ENV, "aura").strip().lower() == "test":
        dsn = os.environ.get("WHYCODE_TEST_POSTGRES_DSN", TEST_POSTGRES_DSN)
    else:
        from whycode.config import get_settings

        dsn = get_settings().postgres_dsn.get_secret_value()
    return GapStore.connect(dsn)


def get_gaps() -> GapStore:
    return _gap_store()


def get_gaps_or_none() -> GapStore | None:
    """For screens that still work without Postgres: no gap store means an empty gap queue."""
    try:
        return _gap_store()
    except (psycopg.Error, ConfigError):
        return None


def repo_param(repo: Annotated[str, Query(description="owner/name")]) -> str:
    return _normalize(repo)


def _normalize(repo: str) -> str:
    try:
        return normalize_repo(repo)
    except ValueError:
        raise HTTPException(400, "repo must look like owner/name") from None


def require_repo(run: Run, repo: str) -> m.Repo:
    found = reads.repo(run, repo)
    if found is None:
        raise HTTPException(404, f"{repo} is not in the graph")
    return found


def require_entity(run: Run, repo: str, entity_id: str) -> m.Entity:
    found = reads.get_entity(run, repo, entity_id)
    if found is None:
        raise HTTPException(404, f"{entity_id} is not in the graph for {repo}")
    return found


def gap_queue(run: Run, gaps: GapStore | None, repo: str, entity_id: str | None = None):
    out = []
    for s in gaps.summaries(repo, entity_id) if gaps else []:
        entity = reads.get_entity(run, repo, s.entity_id)
        if entity is not None:  # an entity that left the graph drops out of the queue
            out.append(
                m.Gap(
                    entity=entity,
                    flags=s.flags,
                    last_question=s.last_question,
                    last_flagged_at=s.last_flagged_at,
                )
            )
    return out


RunDep = Annotated[Run, Depends(get_run)]
RepoDep = Annotated[str, Depends(repo_param)]
router = APIRouter(prefix="/api")


@router.get("/repos", response_model=list[m.Repo])
def list_repos(run: RunDep):
    return reads.repos(run)


@router.get("/overview", response_model=m.Overview)
def get_overview(run: RunDep, repo: RepoDep):
    require_repo(run, repo)
    return reads.overview(run, repo)


@router.get("/explorer", response_model=m.Explorer)
def get_explorer(run: RunDep, repo: RepoDep):
    require_repo(run, repo)
    return reads.explorer(run, repo)


@router.get("/entities/search", response_model=list[m.EntityMatch])
def search_entities(run: RunDep, repo: RepoDep, q: str = ""):
    require_repo(run, repo)
    return reads.search(run, repo, q)


@router.get("/entities", response_model=m.Entity)
def get_entity(run: RunDep, repo: RepoDep, id: str):
    return require_entity(run, repo, id)


@router.post("/ask", response_model=m.Answer)
def ask(run: RunDep, body: m.AskRequest):
    repo_id = _normalize(body.repo)
    repo = require_repo(run, repo_id)
    selected = require_entity(run, repo_id, body.entity_id) if body.entity_id else None
    return answers.ask(run, repo, body.question, selected)


@router.get("/lineage", response_model=m.Lineage)
def get_lineage(run: RunDep, repo: RepoDep, entity_id: str, as_of: date | None = None):
    entity = require_entity(run, repo, entity_id)
    return lineage.lineage(run, repo, entity, as_of)


@router.get("/health", response_model=m.Health)
def get_health(
    run: RunDep, repo: RepoDep, gaps: Annotated[GapStore | None, Depends(get_gaps_or_none)]
):
    found = require_repo(run, repo)
    return reads.health(run, found, gap_queue(run, gaps, repo))


@router.get("/evaluation", response_model=m.Evaluation)
def get_evaluation(run: RunDep, repo: RepoDep):
    found = require_repo(run, repo)
    return reads.evaluation(found.id)


@router.post("/gaps", response_model=m.Gap)
def flag_gap(run: RunDep, body: m.GapRequest, gaps: Annotated[GapStore, Depends(get_gaps)]):
    repo = _normalize(body.repo)
    require_repo(run, repo)
    require_entity(run, repo, body.entity_id)
    gaps.add(repo, body.entity_id, body.question)
    return gap_queue(run, gaps, repo, body.entity_id)[0]


def _not_implemented():
    return JSONResponse(NOT_IMPLEMENTED, status_code=501)


for _method, _path in [
    ("POST", "/repos/check"),
    ("POST", "/repos"),
    ("POST", "/repos/sync"),
    ("POST", "/repos/reingest"),
    ("GET", "/ingestion"),
]:
    router.add_api_route(_path, _not_implemented, methods=[_method], status_code=501)


@asynccontextmanager
async def _lifespan(_app: FastAPI):
    yield
    if _graph.cache_info().currsize:
        _graph()[0].close()
        _graph.cache_clear()
    if _gap_store.cache_info().currsize:
        _gap_store().close()
        _gap_store.cache_clear()


def create_app() -> FastAPI:
    app = FastAPI(title="WhyCode API", lifespan=_lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=CORS_ORIGINS,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type", "Accept"],
    )

    @app.exception_handler(ServiceUnavailable)
    @app.exception_handler(SessionExpired)
    @app.exception_handler(AuthError)
    async def _graph_down(_request: Request, _exc: Exception):
        return JSONResponse(
            {
                "detail": "The graph database is not reachable. If it is the free Aura "
                "instance, resume it in the Aura console."
            },
            status_code=503,
        )

    @app.exception_handler(psycopg.OperationalError)
    async def _postgres_down(_request: Request, _exc: Exception):
        return JSONResponse(
            {"detail": "The gap store (Postgres) is not reachable."}, status_code=503
        )

    @app.exception_handler(ConfigError)
    async def _config(_request: Request, exc: ConfigError):
        return JSONResponse({"detail": str(exc)}, status_code=503)  # names only, never values

    app.include_router(router)
    return app


app = create_app()
