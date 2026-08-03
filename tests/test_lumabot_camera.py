"""Camera tools capture through the daemon, self-prune, and attach photos."""

import pytest

from agent import build_image_attachment_message
from core.interface_context import set_interface
from tool_registry import ToolRegistry
from tools.lumabot import client, photos
from tools.lumabot.photos import (
    get_lumabot_capture_photo_tool,
    get_lumabot_list_photos_tool,
    get_lumabot_trash_photo_tool,
    get_lumabot_view_photo_tool,
)


@pytest.fixture()
def registry():
    result = ToolRegistry()
    for tool in (
        get_lumabot_capture_photo_tool(),
        get_lumabot_list_photos_tool(),
        get_lumabot_view_photo_tool(),
        get_lumabot_trash_photo_tool(),
    ):
        result.register(tool, group="lumabot")
    return result


@pytest.fixture()
def photo_root(tmp_path, monkeypatch):
    monkeypatch.setattr(photos, "PHOTO_ROOT", tmp_path)
    set_interface("web", "owner")
    return tmp_path


def fake_daemon_capture(photo_root, name="visitor-lx1-test.jpg"):
    def _capture():
        source = photo_root / name
        source.write_bytes(b"\xff\xd8jpegdata")
        return {"captured": True, "filename": name, "path": str(source)}

    return _capture


def test_capture_adopts_prunes_and_requests_attachment(
    registry, photo_root, monkeypatch
):
    monkeypatch.setattr(client, "capture_photo", fake_daemon_capture(photo_root))

    result = registry.execute("lumabot_capture_photo", {})

    assert result["success"]
    assert result["data"]["photo_id"] == "visitor-lx1-test.jpg"
    stored = photos.owner_directory() / "visitor-lx1-test.jpg"
    assert stored.exists()
    assert result["data"]["attach_image_path"] == str(stored)
    assert not (photo_root / "visitor-lx1-test.jpg").exists()


def test_capture_enforces_the_keep_limit(registry, photo_root, monkeypatch):
    monkeypatch.setenv("LUMABOT_PHOTO_KEEP", "2")
    for i in range(4):
        monkeypatch.setattr(
            client, "capture_photo", fake_daemon_capture(photo_root, f"shot-{i}.jpg")
        )
        result = registry.execute("lumabot_capture_photo", {})
        assert result["success"]

    kept = list(photos.owner_directory().glob("*.jpg"))
    assert len(kept) == 2


def test_offline_camera_surfaces_as_tool_failure(registry, photo_root, monkeypatch):
    monkeypatch.setattr(
        client,
        "capture_photo",
        lambda: {"error": "LumaBot is offline — is the LumaBot daemon running?"},
    )
    result = registry.execute("lumabot_capture_photo", {})
    assert not result["success"]
    assert "offline" in result["error"]


def test_view_photo_attaches_saved_photo(registry, photo_root, monkeypatch):
    monkeypatch.setattr(client, "capture_photo", fake_daemon_capture(photo_root))
    registry.execute("lumabot_capture_photo", {})

    result = registry.execute(
        "lumabot_view_photo", {"photo_id": "visitor-lx1-test.jpg"}
    )
    assert result["success"]
    assert result["data"]["attach_image_path"].endswith("visitor-lx1-test.jpg")

    missing = registry.execute("lumabot_view_photo", {"photo_id": "nope.jpg"})
    assert not missing["success"]


def test_attachment_message_carries_marked_image(tmp_path):
    photo = tmp_path / "shot.jpg"
    photo.write_bytes(b"\xff\xd8jpegdata")

    message = build_image_attachment_message(str(photo), "lumabot_capture_photo")

    assert message["role"] == "user"
    assert message["tool_image"] is True
    assert message["images"]
    assert "shot.jpg" in message["content"]


def test_attachment_message_rejects_missing_or_non_image(tmp_path):
    assert build_image_attachment_message(str(tmp_path / "gone.jpg"), "t") is None
    text = tmp_path / "notes.txt"
    text.write_text("hello")
    assert build_image_attachment_message(str(text), "t") is None
