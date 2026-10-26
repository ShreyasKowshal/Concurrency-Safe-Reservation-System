"""Document the cookie/CSRF boundary without treating CSRF as authentication."""

from fastapi import FastAPI
from fastapi.openapi.utils import get_openapi

from csrs.config import Settings


def install_auth_schema(app: FastAPI, settings: Settings) -> None:
    def schema():
        if app.openapi_schema is not None:
            return app.openapi_schema
        document = get_openapi(
            title=app.title, version=app.version, description=app.description, routes=app.routes
        )
        document["components"]["securitySchemes"] = {
            "SessionCookie": {
                "type": "apiKey",
                "in": "cookie",
                "name": settings.session_cookie_name,
                "description": "Opaque cookie; anonymous pre-session for register/login.",
            },
            "CsrfToken": {
                "type": "apiKey",
                "in": "header",
                "name": "X-CSRF-Token",
                "description": "Synchronizer token bound to the cookie session.",
            },
        }
        for path, operations in document["paths"].items():
            for method, operation in operations.items():
                limited = (
                    path in {"/api/v1/auth/csrf", "/api/v1/auth/register", "/api/v1/auth/login"}
                    or path.startswith("/api/v1/events")
                    or (
                        method in {"post", "patch"}
                        and path.startswith(("/api/v1/organizer/", "/api/v1/reservations/"))
                    )
                )
                if limited:
                    operation.setdefault("responses", {})["429"] = {
                        "description": "Request quota exceeded (Redis support policy applies).",
                        "headers": {"Retry-After": {"schema": {"type": "integer", "minimum": 1}}},
                        "content": {
                            "application/json": {
                                "schema": {"$ref": "#/components/schemas/ErrorResponse"}
                            }
                        },
                    }
            reservation = path.startswith(
                ("/api/v1/reservations/", "/api/v1/me/reservations")
            ) or path.endswith("/holds")
            if not reservation and not path.startswith(
                ("/api/v1/auth/", "/api/v1/organizer/events")
            ):
                continue
            for method, operation in operations.items():
                if method in {"post", "patch", "put", "delete"}:
                    operation["security"] = [{"SessionCookie": [], "CsrfToken": []}]
                    operation.setdefault("parameters", []).extend(
                        [
                            {
                                "name": "Origin",
                                "in": "header",
                                "required": False,
                                "description": "Trusted Origin, or Referer fallback, is required.",
                                "schema": {"type": "string"},
                            }
                        ]
                    )
                elif (
                    reservation
                    or path.endswith("/me")
                    or path.startswith("/api/v1/organizer/events")
                ):
                    operation["security"] = [{"SessionCookie": []}]
        app.openapi_schema = document
        return document

    app.openapi = schema
