"""
AuthManager - Layer 1 security (spec sections 7-10).

Owns the LOCKED / UNLOCKED state machine:

    LOCKED --authenticate(correct phrase)--> UNLOCKED
    LOCKED --authenticate(wrong phrase)--> LOCKED (attempt counted)
    LOCKED --3rd consecutive wrong attempt--> temporary lockout
    UNLOCKED --manual lock()--> LOCKED

This class never sees where the phrase came from (voice, text, wake
event) - that's the caller's job. It only ever receives a candidate
phrase string and returns a structured AuthResult, never a bare bool,
so callers always have a human-appropriate message to relay (rule 32
principle applied to auth) without needing their own copy of the
security logic.

The phrase itself is never logged: AuthResult.message is a
pre-written, generic sentence, and this module never interpolates the
phrase into any string that could reach a log file.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from enum import Enum
from typing import Callable

from app.auth.hashing import verify_phrase
from app.auth.pin import normalize_pin
from app.auth.session import Session
from app.auth.store import SecretStore
from app.config import SecurityConfig
from app.logging import get_logger, log_event

logger = get_logger("auth.manager")


class AuthState(str, Enum):
    LOCKED = "LOCKED"
    UNLOCKED = "UNLOCKED"


@dataclass
class AuthResult:
    success: bool
    message: str
    locked_out: bool = False


class AuthManager:
    def __init__(
        self,
        security_config: SecurityConfig,
        secret_store: SecretStore,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._config = security_config
        self._store = secret_store
        self._clock = clock
        self._state = AuthState.LOCKED
        self._failed_attempts = 0
        self._lockout_until: float | None = None
        self._session = Session(
            timeout_seconds=security_config.session_timeout_minutes * 60,
            clock=clock,
        )

    # --- queries -----------------------------------------------------

    @property
    def state(self) -> AuthState:
        return self._state

    def is_locked_out(self) -> bool:
        return self._lockout_until is not None and self._clock() < self._lockout_until

    def lockout_remaining_seconds(self) -> int:
        if self._lockout_until is None:
            return 0
        return max(0, int(self._lockout_until - self._clock()))

    def is_unlocked(self) -> bool:
        """
        True if currently UNLOCKED. Victor stays active after successful
        verification until the user explicitly locks it.
        """
        return self._state is AuthState.UNLOCKED

    def is_configured(self) -> bool:
        return self._store.is_configured()

    # --- transitions ---------------------------------------------------

    def authenticate(self, phrase: str) -> AuthResult:
        if self.is_locked_out():
            remaining = self.lockout_remaining_seconds()
            log_event(logger, logging.WARNING, "auth_attempt_while_locked_out", remaining_seconds=remaining)
            return AuthResult(
                success=False,
                message=(
                    f"Too many failed attempts, Sir. Please try again in "
                    f"{remaining} seconds."
                ),
                locked_out=True,
            )

        if not self._store.is_configured():
            log_event(logger, logging.ERROR, "auth_attempted_before_provisioning")
            return AuthResult(
                success=False,
                message=(
                    "Authentication isn't set up yet, Sir. Run the setup "
                    "script to configure a security phrase first."
                ),
            )

        stored_hash = self._store.get_phrase_hash()
        candidate = normalize_pin(phrase) if self._config.auth_mode == "pin" else phrase
        # verify_phrase never raises and never logs the candidate phrase.
        if stored_hash and verify_phrase(candidate, stored_hash):
            self._failed_attempts = 0
            self._lockout_until = None
            self._state = AuthState.UNLOCKED
            self._session.start()
            log_event(logger, logging.INFO, "auth_success")
            return AuthResult(success=True, message="Verified, Sir.")

        self._failed_attempts += 1
        log_event(
            logger, logging.WARNING, "auth_failure", failed_attempts=self._failed_attempts
        )

        if self._failed_attempts >= self._config.max_failed_attempts:
            self._lockout_until = self._clock() + self._config.lockout_seconds
            self._failed_attempts = 0
            log_event(
                logger,
                logging.WARNING,
                "auth_lockout_triggered",
                lockout_seconds=self._config.lockout_seconds,
            )
            return AuthResult(
                success=False,
                message=(
                    "Verification failed, Sir. Too many attempts - "
                    f"locking for {self._config.lockout_seconds} seconds."
                ),
                locked_out=True,
            )

        return AuthResult(success=False, message="Verification failed, Sir.")

    def touch_activity(self) -> None:
        """Record activity for the currently authenticated session."""
        if self._state is AuthState.UNLOCKED:
            self._session.extend()

    def lock(self) -> None:
        """Manual lock (spec section 10: 'Victor, lock yourself' / UI button),
        also used internally on session timeout."""
        was_unlocked = self._state is AuthState.UNLOCKED
        self._state = AuthState.LOCKED
        self._session.end()
        if was_unlocked:
            log_event(logger, logging.INFO, "auth_locked")
