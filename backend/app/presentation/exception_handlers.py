from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError

from app.domain.exceptions import (
    DomainValidationException,
    InsufficientVerifiedDataException,
    ResourceNotFoundException,
    TaskTypeMismatchException,
    UnverifiedDataException,
)


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(DomainValidationException)
    async def domain_validation_handler(
        _request: Request, exc: DomainValidationException
    ) -> JSONResponse:
        return JSONResponse(status_code=422, content={"detail": str(exc)})

    @app.exception_handler(ResourceNotFoundException)
    async def not_found_handler(
        _request: Request, exc: ResourceNotFoundException
    ) -> JSONResponse:
        return JSONResponse(status_code=404, content={"detail": str(exc)})

    @app.exception_handler(UnverifiedDataException)
    async def unverified_handler(
        _request: Request, exc: UnverifiedDataException
    ) -> JSONResponse:
        return JSONResponse(status_code=400, content={"detail": str(exc)})

    @app.exception_handler(InsufficientVerifiedDataException)
    async def insufficient_verified_handler(
        _request: Request, exc: InsufficientVerifiedDataException
    ) -> JSONResponse:
        return JSONResponse(status_code=400, content={"detail": str(exc)})

    @app.exception_handler(TaskTypeMismatchException)
    async def task_type_handler(
        _request: Request, exc: TaskTypeMismatchException
    ) -> JSONResponse:
        return JSONResponse(status_code=409, content={"detail": str(exc)})

    @app.exception_handler(IntegrityError)
    async def integrity_handler(_request: Request, exc: IntegrityError) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content={"detail": "unique constraint violated"},
        )
