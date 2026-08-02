from pathlib import Path

from core.interface_context import set_interface
from tools.lumabot import photos


def test_capture_is_adopted_into_private_user_directory(tmp_path, monkeypatch):
    monkeypatch.setattr(photos, "PHOTO_ROOT", tmp_path)
    set_interface("telegram", "pat-private-id")
    source = tmp_path / "visitor-lx1-test.jpg"
    source.write_bytes(b"jpeg")

    target = photos.adopt_capture(str(source))

    assert target.read_bytes() == b"jpeg"
    assert target.parent.parent.name == "users"
    assert "pat-private-id" not in str(target)
    assert target.stat().st_mode & 0o777 == 0o600


def test_capture_outside_camera_inbox_is_rejected(tmp_path, monkeypatch):
    monkeypatch.setattr(photos, "PHOTO_ROOT", tmp_path / "photos")
    set_interface("web", "owner")
    outside = tmp_path / "outside.jpg"
    outside.write_bytes(b"jpeg")

    try:
        photos.adopt_capture(str(outside))
    except ValueError as error:
        assert "invalid photo path" in str(error)
    else:
        raise AssertionError("outside photo was accepted")


def test_photos_are_listed_and_moved_to_recoverable_trash(tmp_path, monkeypatch):
    monkeypatch.setattr(photos, "PHOTO_ROOT", tmp_path)
    set_interface("telegram", "pat")
    source = tmp_path / "visitor-lx1-newest.jpg"
    source.write_bytes(b"jpeg")
    stored = photos.adopt_capture(str(source))

    assert photos.list_photos()[0]["photo_id"] == stored.name
    trashed = photos.trash_photo(stored.name)
    assert trashed.parent.name == ".trash"
    assert trashed.exists()
    assert photos.list_photos() == []


def test_photo_delete_rejects_path_traversal(tmp_path, monkeypatch):
    monkeypatch.setattr(photos, "PHOTO_ROOT", tmp_path)
    set_interface("web", "owner")

    try:
        photos.trash_photo("../someone-elses-photo.jpg")
    except ValueError as error:
        assert "photo_id" in str(error)
    else:
        raise AssertionError("path traversal was accepted")
