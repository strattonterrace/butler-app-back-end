"""General helpers — kept tiny and side-effect free."""
import secrets
import string


def generate_temp_password(length: int = 16) -> str:
    """Cryptographically random temporary password (used by admin operator-create)."""
    alphabet = string.ascii_letters + string.digits + "!@#$%^&*"
    return "".join(secrets.choice(alphabet) for _ in range(length))
