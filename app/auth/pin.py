"""Argon2 PIN hashing. Rationale: see app/auth/__init__.py.

Usage: python -m app.auth.pin 1234   (prints a hash for the OWNER_PIN_HASH env var)
"""

import sys

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError

_hasher = PasswordHasher()


def hash_pin(pin: str) -> str:
    return _hasher.hash(pin)


def verify_pin(pin: str, pin_hash: str) -> bool:
    try:
        return _hasher.verify(pin_hash, pin)
    except (VerifyMismatchError, InvalidHashError):
        return False


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("usage: python -m app.auth.pin <pin>")
    print(hash_pin(sys.argv[1]))
