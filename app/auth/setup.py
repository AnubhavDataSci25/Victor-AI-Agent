"""
Setup / provisioning utility for Victor 2.0 authentication credentials.

Usage:
    python -m app.auth.setup --pin 1234
    python -m app.auth.setup --passphrase "my secret passphrase"
    python -m app.auth.setup (interactive prompt)
"""

from __future__ import annotations

import argparse
import getpass
import sys
from pathlib import Path

from dotenv import load_dotenv

# Ensure environment is loaded
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_ENV_FILE = _PROJECT_ROOT / ".env"
if _ENV_FILE.exists():
    load_dotenv(_ENV_FILE)
else:
    load_dotenv()

from app.auth.hashing import hash_phrase
from app.auth.pin import normalize_pin
from app.auth.store import SecretStore
from app.config import load_config


def configure_credentials(phrase: str, auth_mode: str = "pin", secrets_path: str | None = None) -> None:
    config = load_config()
    target_path = secrets_path or config.security.secrets_path
    store = SecretStore(target_path)

    if auth_mode == "pin":
        normalized = normalize_pin(phrase)
        if not normalized.isdigit():
            raise ValueError(f"PIN must contain only digits, received: {phrase!r}")
        if len(normalized) < 4:
            raise ValueError("PIN must be at least 4 digits long.")
        hashed = hash_phrase(normalized)
    else:
        if not phrase or len(phrase.strip()) < 4:
            raise ValueError("Passphrase must be at least 4 characters long.")
        hashed = hash_phrase(phrase)

    store.set_phrase_hash(hashed)
    print(f"[OK] Victor credentials successfully configured at: {target_path}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Configure Victor 2.0 authentication credentials.")
    parser.add_argument("--pin", type=str, help="PIN code to configure (digits only).")
    parser.add_argument("--passphrase", type=str, help="Passphrase to configure.")
    parser.add_argument("--path", type=str, help="Custom secrets.yaml file path.")
    args = parser.parse_args()

    config = load_config()
    auth_mode = config.security.auth_mode

    if args.pin:
        configure_credentials(args.pin, auth_mode="pin", secrets_path=args.path)
    elif args.passphrase:
        configure_credentials(args.passphrase, auth_mode="passphrase", secrets_path=args.path)
    else:
        # Interactive mode
        print(f"=== Victor 2.0 Credential Setup (Mode: {auth_mode}) ===")
        if auth_mode == "pin":
            entered = getpass.getpass("Enter new PIN (digits only): ").strip()
            confirm = getpass.getpass("Confirm new PIN: ").strip()
        else:
            entered = getpass.getpass("Enter new passphrase: ").strip()
            confirm = getpass.getpass("Confirm new passphrase: ").strip()

        if entered != confirm:
            print("[ERROR] Credentials do not match. Aborting.", file=sys.stderr)
            sys.exit(1)

        try:
            configure_credentials(entered, auth_mode=auth_mode, secrets_path=args.path)
        except Exception as e:
            print(f"[ERROR] {e}", file=sys.stderr)
            sys.exit(1)


if __name__ == "__main__":
    main()
