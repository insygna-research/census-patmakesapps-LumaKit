"""Private per-user storage for LumaBot camera photos, plus the camera tools.

The daemon writes captures into a shared inbox (PHOTO_ROOT); each capture is
immediately adopted into a private per-user library. The library is
self-pruning so photos can never eat the Pi's storage: only the newest
LUMABOT_PHOTO_KEEP (default 20) are kept, trashed photos are purged after a
week, and stale inbox strays are cleaned up on every capture.
"""

import os
import time
from hashlib import sha256
from pathlib import Path

from core.interface_context import get_interface, get_interface_user
from tools.lumabot import client


PHOTO_ROOT = Path.home() / ".visitor-lx1" / "photos"
TRASH_MAX_AGE_S = 7 * 24 * 3600
INBOX_MAX_AGE_S = 3600


def photo_keep_limit() -> int:
    try:
        return max(1, int(os.getenv("LUMABOT_PHOTO_KEEP", "20")))
    except ValueError:
        return 20


def owner_directory() -> Path:
    """Return a private directory without exposing the surface user ID."""
    surface = get_interface() or "local"
    user_id = get_interface_user() or "owner"
    owner_key = sha256(f"{surface}:{user_id}".encode()).hexdigest()[:16]
    directory = PHOTO_ROOT / "users" / owner_key
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    directory.chmod(0o700)
    return directory


def adopt_capture(raw_path: str) -> Path:
    """Move one daemon-created inbox JPEG into the current user's library."""
    source = Path(raw_path).resolve()
    if source.parent != PHOTO_ROOT.resolve() or source.suffix.lower() != ".jpg":
        raise ValueError("camera returned an invalid photo path")
    target = owner_directory() / source.name
    if target.exists():
        raise FileExistsError(f"photo already exists: {target.name}")
    source.rename(target)
    target.chmod(0o600)
    return target


def prune_library() -> int:
    """Keep only the newest photos; purge old trash. Returns photos deleted."""
    directory = owner_directory()
    photos = sorted(
        (p for p in directory.glob("*.jpg") if p.is_file() and not p.is_symlink()),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    removed = 0
    for stale in photos[photo_keep_limit():]:
        stale.unlink(missing_ok=True)
        removed += 1
    trash = directory / ".trash"
    if trash.is_dir():
        cutoff = time.time() - TRASH_MAX_AGE_S
        for item in trash.glob("*.jpg"):
            if item.is_file() and item.stat().st_mtime < cutoff:
                item.unlink(missing_ok=True)
    return removed


def clean_inbox() -> int:
    """Delete inbox strays left behind by crashed adoptions. Returns count."""
    if not PHOTO_ROOT.is_dir():
        return 0
    cutoff = time.time() - INBOX_MAX_AGE_S
    removed = 0
    for stray in PHOTO_ROOT.glob("*.jpg"):
        if stray.is_file() and not stray.is_symlink() and stray.stat().st_mtime < cutoff:
            stray.unlink(missing_ok=True)
            removed += 1
    return removed


def list_photos() -> list[dict]:
    """List the current user's captured photos, newest first."""
    results = []
    for path in sorted(owner_directory().glob("*.jpg"), reverse=True):
        if path.is_file() and not path.is_symlink():
            results.append({
                "photo_id": path.name,
                "captured_at": path.stat().st_mtime,
                "bytes": path.stat().st_size,
                "path": str(path),
            })
    return results


def trash_photo(photo_id: str) -> Path:
    """Move one current-user photo to private recoverable trash."""
    if not isinstance(photo_id, str) or Path(photo_id).name != photo_id:
        raise ValueError("photo_id must be a filename from the photo list")
    directory = owner_directory()
    source = directory / photo_id
    if source.suffix.lower() != ".jpg" or not source.is_file() or source.is_symlink():
        raise FileNotFoundError(f"photo not found: {photo_id}")
    trash = directory / ".trash"
    trash.mkdir(mode=0o700, exist_ok=True)
    trash.chmod(0o700)
    target = trash / source.name
    if target.exists():
        raise FileExistsError(f"photo is already in trash: {photo_id}")
    source.rename(target)
    target.chmod(0o600)
    return target


def _resolve_library_photo(photo_id: str) -> Path:
    if not isinstance(photo_id, str) or Path(photo_id).name != photo_id:
        raise ValueError("photo_id must be a filename from the photo list")
    path = owner_directory() / photo_id
    if path.suffix.lower() != ".jpg" or not path.is_file() or path.is_symlink():
        raise FileNotFoundError(f"photo not found: {photo_id}")
    return path


def _execute_capture(inputs: dict) -> dict:
    result = client.capture_photo()
    if result.get("error"):
        return {"error": result["error"]}
    raw_path = result.get("path")
    if not raw_path:
        return {"error": "the camera did not return a photo path"}
    try:
        stored = adopt_capture(str(raw_path))
    except (ValueError, FileExistsError, OSError) as exc:
        return {"error": f"could not store the photo: {exc}"}
    pruned = prune_library()
    clean_inbox()
    return {
        "success": True,
        "photo_id": stored.name,
        "pruned_old_photos": pruned,
        "attach_image_path": str(stored),
        "note": (
            "The photo arrives as the next message. Describe only what is "
            "actually visible in it."
        ),
    }


def _execute_view(inputs: dict) -> dict:
    try:
        path = _resolve_library_photo(str(inputs.get("photo_id", "")))
    except (ValueError, FileNotFoundError) as exc:
        return {"error": str(exc)}
    return {
        "success": True,
        "photo_id": path.name,
        "attach_image_path": str(path),
        "note": "The photo arrives as the next message.",
    }


def _execute_trash(inputs: dict) -> dict:
    try:
        trash_photo(str(inputs.get("photo_id", "")))
    except (ValueError, FileNotFoundError, FileExistsError) as exc:
        return {"error": str(exc)}
    return {"success": True, "trashed": inputs.get("photo_id")}


def get_lumabot_capture_photo_tool():
    return {
        "name": "lumabot_capture_photo",
        "description": (
            "Take one real photo with LumaBot's forward camera and look at it. "
            "Use when the user asks what the robot sees, to look around, to "
            "check on something, or when understanding the surroundings would "
            "help. The capture takes a few seconds; the photo then arrives as "
            "the next message for you to examine. The library keeps only the "
            "newest photos and prunes the rest automatically. Describe what "
            "you actually see — never invent detail the photo does not show."
        ),
        "inputSchema": {"type": "object", "properties": {}},
        "execute": _execute_capture,
    }


def get_lumabot_list_photos_tool():
    return {
        "name": "lumabot_list_photos",
        "description": (
            "List the saved LumaBot camera photos (newest first) with their "
            "photo_id, capture time, and size. Use before viewing or trashing "
            "a specific photo."
        ),
        "inputSchema": {"type": "object", "properties": {}},
        "execute": lambda inputs: {"success": True, "photos": list_photos()},
    }


def get_lumabot_view_photo_tool():
    return {
        "name": "lumabot_view_photo",
        "description": (
            "Re-examine one previously captured LumaBot photo by photo_id "
            "(from lumabot_list_photos). The photo arrives as the next "
            "message for you to look at."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "photo_id": {
                    "type": "string",
                    "description": "Filename from lumabot_list_photos",
                }
            },
            "required": ["photo_id"],
        },
        "execute": _execute_view,
    }


def get_lumabot_trash_photo_tool():
    return {
        "name": "lumabot_trash_photo",
        "description": (
            "Move one saved LumaBot photo to recoverable trash by photo_id. "
            "Trash is purged automatically after a week."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "photo_id": {
                    "type": "string",
                    "description": "Filename from lumabot_list_photos",
                }
            },
            "required": ["photo_id"],
        },
        "execute": _execute_trash,
    }
