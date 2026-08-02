"""Private per-user storage for VISITOR LX-1 photos."""

from hashlib import sha256
from pathlib import Path

from core.interface_context import get_interface, get_interface_user


PHOTO_ROOT = Path.home() / ".visitor-lx1" / "photos"


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
