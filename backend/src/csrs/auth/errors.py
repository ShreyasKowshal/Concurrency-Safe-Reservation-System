class AuthError(Exception):
    def __init__(self, status: int, code: str, message: str):
        self.status = status
        self.code = code
        self.message = message
        super().__init__(code)


def csrf_failed() -> AuthError:
    return AuthError(403, "CSRF_FAILED", "A valid session token and trusted origin are required.")


def authentication_required() -> AuthError:
    return AuthError(401, "AUTHENTICATION_REQUIRED", "Authentication is required.")


def invalid_credentials() -> AuthError:
    return AuthError(401, "INVALID_CREDENTIALS", "Invalid email or password.")
