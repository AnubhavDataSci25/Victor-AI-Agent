# Project Rules & Security Guidelines

## 1. Secret & Credential Protection (Zero-Leak Policy)
- **NEVER** hardcode real API keys, secrets, passwords, PINs, or private tokens in any source code, tests, documentation, config files, or commit messages.
- **Always** use dummy/mock placeholders for unit tests (e.g., `"AIzaSyDummyKeyForTesting1234567890abcde"`, `"sk-1234567890abcdef1234567890abcdef"`).
- Real secrets must strictly be loaded from environment variables (e.g., via `.env` or `os.getenv`).
- Never print or output actual secret values into logs, chat outputs, or artifacts.
