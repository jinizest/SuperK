"""Persistent installation identity for the Korail client (no network calls)."""
import json
import os
from pathlib import Path
import re
import secrets
import tempfile


def _validate_device_id(value):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-fA-F]{16}", value):
        raise ValueError("Korail device ID must be 16 hexadecimal characters")
    return value.lower()


def load_device_id():
    """Reuse an explicit ID or atomically persist one ID per installation.

    A damaged or unwritable identity file is an error, not permission to change
    identity on each retry. Concurrent clients reuse the first published file.
    """
    explicit = os.environ.get("KORAIL_DEVICE_ID", "").strip()
    if explicit:
        return _validate_device_id(explicit)
    configured_path = os.environ.get("KORAIL_DEVICE_FILE", "").strip()
    path = Path(configured_path).expanduser() if configured_path else (
        Path.home() / ".config" / "superk" / "korail-device.json"
    )

    def read_existing():
        with path.open(encoding="utf-8") as stream:
            data = json.load(stream)
        if not isinstance(data, dict) or data.get("schema_version") != 1:
            raise ValueError("Invalid Korail device file schema")
        return _validate_device_id(data.get("device_id"))

    try:
        return read_existing()
    except FileNotFoundError:
        pass
    path.parent.mkdir(parents=True, exist_ok=True)
    device_id = secrets.token_hex(8)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=path.parent,
            prefix=".korail-device-", delete=False,
        ) as stream:
            temporary = Path(stream.name)
            json.dump({"schema_version": 1, "device_id": device_id}, stream)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            # Publish a complete file without replacing another client's ID.
            os.link(temporary, path)
        except FileExistsError:
            return read_existing()
        return device_id
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
