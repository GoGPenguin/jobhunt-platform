"""Credentials from the environment or ~/.config/jobhunt/secrets.env (Docker Compose phase).

The environment wins over the file. The file must not be readable by other users. Values never
appear in errors, reprs or logs (see jobhunt.logs). Moved to SOPS / External Secrets in the
Kubernetes phase. See plan 02A, task 3.
"""

import os
import re
from collections.abc import Mapping
from pathlib import Path

from pydantic import BaseModel, ConfigDict, SecretStr

from jobhunt.config_files import ConfigError

DEFAULT_SECRETS_PATH = Path.home() / ".config" / "jobhunt" / "secrets.env"
IMAP_USER = "JOBHUNT_IMAP_USER"
IMAP_PASSWORD = "JOBHUNT_IMAP_APP_PASSWORD"  # noqa: S105 - variable name, not a value

_KEY = re.compile(r"[A-Z_][A-Z0-9_]*")


class ImapCredentials(BaseModel):
    model_config = ConfigDict(frozen=True)

    user: str
    password: SecretStr  # repr and str show '**********'


def read_secrets_file(path: Path) -> dict[str, str]:
    """Parse KEY=VALUE lines (`#` comments, optional `export`, optional quotes). A missing file
    is empty. Refuses a file that group or others can access."""
    if not path.exists():
        return {}
    if path.stat().st_mode & 0o077:
        raise ConfigError(f"{path}: readable by other users; run: chmod 600 {path}")
    values: dict[str, str] = {}
    for number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        key, has_equals, value = line.removeprefix("export ").partition("=")
        key, value = key.strip(), value.strip()
        if not has_equals or not _KEY.fullmatch(key):
            raise ConfigError(f"{path}: line {number} is not KEY=VALUE")  # never echo the line
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
            value = value[1:-1]
        values[key] = value
    return values


def imap_credentials(
    env: Mapping[str, str] = os.environ, secrets_path: Path = DEFAULT_SECRETS_PATH
) -> ImapCredentials:
    from_env = {k: env[k] for k in (IMAP_USER, IMAP_PASSWORD) if k in env}
    values = read_secrets_file(secrets_path) | from_env
    missing = [k for k in (IMAP_USER, IMAP_PASSWORD) if not values.get(k)]
    if missing:
        raise ConfigError(f"missing {', '.join(missing)}: set in the environment or {secrets_path}")
    return ImapCredentials(user=values[IMAP_USER], password=SecretStr(values[IMAP_PASSWORD]))
