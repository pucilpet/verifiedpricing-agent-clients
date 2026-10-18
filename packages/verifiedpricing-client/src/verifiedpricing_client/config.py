"""Private, atomic configuration; never discovers or reads project .env files."""

import json
import os
from pathlib import Path
import stat
import tempfile

from .client import ClientError, validate_base_url, validate_key

MAX_CONFIG_BYTES = 8192


def default_path():
    return Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "verifiedpricing" / "config.json"


def load(path):
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except FileNotFoundError:
        return {}
    except OSError:
        raise ClientError("configuration", "Cannot safely open private configuration") from None
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or stat.S_IMODE(info.st_mode) != 0o600 or info.st_uid != os.getuid():
            raise ClientError("configuration", "Configuration must be an owned regular file with mode 0600")
        with os.fdopen(descriptor, "rb") as stream:
            descriptor = None
            raw = stream.read(MAX_CONFIG_BYTES + 1)
        if len(raw) > MAX_CONFIG_BYTES:
            raise ValueError()
        result = json.loads(raw)
        if not isinstance(result, dict) or set(result) - {"api_key", "base_url"}:
            raise ValueError()
        validate_key(result.get("api_key"))
        # Local HTTP requires a per-invocation opt-in, even when saved.
        validate_base_url(result.get("base_url", "https://verifiedpricing.com"), True)
        return result
    except (ValueError, UnicodeError):
        raise ClientError("configuration", "Invalid private configuration") from None
    finally:
        if descriptor is not None:
            os.close(descriptor)


def save(path, *, api_key, base_url, allow_localhost=False):
    validate_key(api_key)
    validate_base_url(base_url, allow_localhost)
    path = Path(path)
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    parent = path.parent.stat()
    if parent.st_uid != os.getuid() or stat.S_IMODE(parent.st_mode) & 0o077:
        raise ClientError("configuration", "Configuration directory must be private and owned")
    if path.is_symlink():
        raise ClientError("configuration", "Refusing a configuration symlink")
    descriptor, temporary = tempfile.mkstemp(prefix=".config-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            os.fchmod(stream.fileno(), 0o600)
            json.dump({"api_key": api_key, "base_url": base_url}, stream, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
