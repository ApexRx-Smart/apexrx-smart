"""Application errors and translation of database errors into HTTP responses.

Routes validate business rules first and raise ``AppError`` subclasses with
clear messages. The database triggers and constraints are the backstop; if one
of them fires anyway, the handlers below return a 409 instead of a 500.
"""

import logging

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse
from sqlalchemy.exc import DBAPIError, IntegrityError

logger = logging.getLogger("apexrx")


class AppError(Exception):
    status_code = status.HTTP_400_BAD_REQUEST

    def __init__(
        self,
        detail: str,
        *,
        status_code: int | None = None,
        extra: dict | None = None,
        headers: dict[str, str] | None = None,
    ):
        super().__init__(detail)
        self.detail = detail
        self.extra = extra or {}
        self.headers = headers or {}
        if status_code is not None:
            self.status_code = status_code


class NotFound(AppError):
    status_code = status.HTTP_404_NOT_FOUND


class Forbidden(AppError):
    status_code = status.HTTP_403_FORBIDDEN


class Conflict(AppError):
    status_code = status.HTTP_409_CONFLICT


class Unauthorized(AppError):
    status_code = status.HTTP_401_UNAUTHORIZED


class TooManyRequests(AppError):
    status_code = status.HTTP_429_TOO_MANY_REQUESTS


def _pg_message(exc: DBAPIError) -> tuple[str | None, str]:
    orig = getattr(exc, "orig", None)
    sqlstate = getattr(orig, "sqlstate", None)
    diag = getattr(orig, "diag", None)
    message = getattr(diag, "message_primary", None) or str(orig or exc).splitlines()[0]
    return sqlstate, message


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error(_: Request, exc: AppError):
        headers = dict(exc.headers)
        if isinstance(exc, Unauthorized):
            headers["WWW-Authenticate"] = "Bearer"
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": exc.detail, **exc.extra},
            headers=headers or None,
        )

    @app.exception_handler(IntegrityError)
    async def _integrity_error(_: Request, exc: IntegrityError):
        sqlstate, message = _pg_message(exc)
        logger.info("Integrity error %s: %s", sqlstate, message)
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content={"detail": "The request conflicts with existing data.", "reason": message},
        )

    @app.exception_handler(DBAPIError)
    async def _db_error(_: Request, exc: DBAPIError):
        sqlstate, message = _pg_message(exc)
        # P0001 = RAISE EXCEPTION from one of the schema's business-rule triggers.
        if sqlstate == "P0001":
            return JSONResponse(
                status_code=status.HTTP_409_CONFLICT,
                content={"detail": message},
            )
        logger.exception("Database error %s", sqlstate)
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={"detail": "A database error occurred. Please try again."},
        )
