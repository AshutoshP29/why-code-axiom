"""The WhyCode API for the screens: every path under /api, every call scoped to one repo.

    uv run uvicorn whycode.api.app:app --reload --port 8000

WHYCODE_GRAPH_TARGET picks the Neo4j database: "aura" (default, needs .env) or "test" (the
docker-compose container). The driver is made on the first request, so importing this module
needs no configuration.
"""

import os
from contextlib import asynccontextmanager
from functools import lru_cache
from typing import Annotated

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from neo4j.exceptions import AuthError, ServiceUnavailable, SessionExpired

from whycode.api import models as m
from whycode.api import reads
from whycode.config import ConfigError
from whycode.graph.queries import Run, neo4j_runner
from whycode.ids import normalize_repo

TARGET_ENV = "WHYCODE_GRAPH_TARGET"
CORS_ORIGINS = ["http://localhost:5173", "http://127.0.0.1:5173"]
NOT_IMPLEMENTED = {"detail": "not implemented yet"}


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


RunDep = Annotated[Run, Depends(get_run)]
RepoDep = Annotated[str, Depends(repo_param)]
router = APIRouter(prefix="/api")


@router.get("/repos", response_model=list[m.Repo])
def list_repos(run: RunDep):
    return reads.repos(run)


@router.get("/entities/search", response_model=list[m.EntityMatch])
def search_entities(run: RunDep, repo: RepoDep, q: str = ""):
    require_repo(run, repo)
    return reads.search(run, repo, q)


@router.get("/entities", response_model=m.Entity)
def get_entity(run: RunDep, repo: RepoDep, id: str):
    return require_entity(run, repo, id)


def _not_implemented():
    return JSONResponse(NOT_IMPLEMENTED, status_code=501)


for _method, _path in [
    ("POST", "/repos/check"),
    ("POST", "/repos"),
    ("POST", "/repos/sync"),
    ("POST", "/repos/reingest"),
    ("GET", "/ingestion"),
    ("GET", "/evaluation"),
]:
    router.add_api_route(_path, _not_implemented, methods=[_method], status_code=501)


@asynccontextmanager
async def _lifespan(_app: FastAPI):
    yield
    if _graph.cache_info().currsize:
        _graph()[0].close()
        _graph.cache_clear()


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

    @app.exception_handler(ConfigError)
    async def _config(_request: Request, exc: ConfigError):
        return JSONResponse({"detail": str(exc)}, status_code=503)  # names only, never values

    app.include_router(router)
    return app


app = create_app()
