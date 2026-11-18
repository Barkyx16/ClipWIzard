import functools
import http.server
import shutil
import threading
import time

import pytest
from fastapi.testclient import TestClient

from app.media import importer


@pytest.fixture()
def file_server(demo_video, tmp_path, monkeypatch):
    """Serves demo.mp4 (and a redirect) from 127.0.0.1."""
    root = tmp_path / "www"
    root.mkdir()
    shutil.copy(demo_video, root / "session.mp4")
    (root / "page.mp4").write_text("<html>not a video</html>")

    class Handler(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_GET(self):
            if self.path == "/redirect-private.mp4":
                self.send_response(302)
                self.send_header("Location", "http://10.0.0.1/secret.mp4")
                self.end_headers()
                return
            if self.path == "/page.mp4":
                body = b"<html>not a video</html>"
                self.send_response(200)
                self.send_header("Content-Type", "text/html")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            return super().do_GET()

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(Handler, directory=str(root)))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    monkeypatch.setenv("NO_PROXY", "127.0.0.1,localhost")
    monkeypatch.setenv("no_proxy", "127.0.0.1,localhost")
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()


@pytest.mark.parametrize("url,kind", [
    ("https://www.youtube.com/watch?v=abc123", "platform"),
    ("https://youtu.be/abc123", "platform"),
    ("https://www.twitch.tv/videos/123456", "platform"),
    ("https://clips.twitch.tv/SomeClip", "platform"),
    ("https://kick.com/video/abc", "platform"),
    ("https://medal.tv/games/gta/clips/abc", "platform"),
    ("https://cdn.example.com/vods/session.MP4?sig=1", "direct"),
])
def test_classify_accepts(url, kind):
    assert importer.classify(url)[0] == kind


@pytest.mark.parametrize("url", [
    "ftp://example.com/a.mp4",
    "https://example.com/watch?v=1",
    "https://user:pw@example.com/a.mp4",
    "not a url",
    "https://evil-youtube.com.attacker.net/a",
])
def test_classify_rejects(url):
    with pytest.raises(importer.ImportFailed):
        importer.classify(url)


def test_private_addresses_are_blocked(monkeypatch):
    monkeypatch.delenv("CLIPWIZARD_ALLOW_PRIVATE_URLS", raising=False)
    for host in ("127.0.0.1", "10.1.2.3", "169.254.169.254", "192.168.0.10", "::1"):
        with pytest.raises(importer.ImportFailed):
            importer._check_public(host, 80)


def test_redirects_to_private_addresses_are_blocked(monkeypatch):
    monkeypatch.delenv("CLIPWIZARD_ALLOW_PRIVATE_URLS", raising=False)
    handler = importer._SafeRedirects()
    with pytest.raises(importer.ImportFailed):
        handler.redirect_request(None, None, 302, "Found", {}, "http://169.254.169.254/latest")
    with pytest.raises(importer.ImportFailed):
        handler.redirect_request(None, None, 302, "Found", {}, "file:///etc/passwd")


def test_direct_download(file_server, tmp_path, monkeypatch):
    monkeypatch.setenv("CLIPWIZARD_ALLOW_PRIVATE_URLS", "1")
    seen = []
    out = importer.download_direct(f"{file_server}/session.mp4", tmp_path / "x.mp4", 50 * 2**20, seen.append)
    assert out.stat().st_size > 100_000 and seen[-1] == 1.0
    with pytest.raises(importer.ImportFailed, match="larger"):
        importer.download_direct(f"{file_server}/session.mp4", tmp_path / "y.mp4", 1000)
    with pytest.raises(importer.ImportFailed, match="web page"):
        importer.download_direct(f"{file_server}/page.mp4", tmp_path / "z.mp4", 2**20)
    with pytest.raises(importer.ImportFailed, match="404"):
        importer.download_direct(f"{file_server}/missing.mp4", tmp_path / "w.mp4", 2**20)
    assert not list(tmp_path.glob("*.part"))


def test_direct_download_refuses_private_without_override(file_server, tmp_path, monkeypatch):
    monkeypatch.delenv("CLIPWIZARD_ALLOW_PRIVATE_URLS", raising=False)
    with pytest.raises(importer.ImportFailed, match="private"):
        importer.download_direct(f"{file_server}/session.mp4", tmp_path / "x.mp4", 2**30)


def _wait(client, url, timeout=90):
    deadline = time.time() + timeout
    while time.time() < deadline:
        body = client.get(url).json()
        if body["status"] in ("ready", "failed"):
            return body
        time.sleep(0.3)
    raise AssertionError(body)


def test_import_api_direct_link(file_server, monkeypatch):
    from app.main import app

    monkeypatch.setenv("CLIPWIZARD_ALLOW_PRIVATE_URLS", "1")
    with TestClient(app) as client:
        r = client.post("/api/videos/import", json={"url": f"{file_server}/session.mp4", "max_clips": 3})
        assert r.status_code == 201, r.text
        assert r.json()["status"] == "downloading"
        video = _wait(client, f"/api/videos/{r.json()['id']}")
        assert video["status"] == "ready", video["error"]
        assert video["duration"] == pytest.approx(90, abs=0.5)
        assert video["name"] == "session.mp4"
        assert len(video["highlights"]) == 3
        assert client.get(video["source_url"]).status_code == 200

        bad = client.post("/api/videos/import", json={"url": "https://example.com/watch"})
        assert bad.status_code == 400

        failed = client.post("/api/videos/import", json={"url": f"{file_server}/missing.mp4"}).json()
        failed = _wait(client, f"/api/videos/{failed['id']}")
        assert failed["status"] == "failed" and "404" in failed["error"]
        assert client.delete(f"/api/videos/{failed['id']}").status_code == 204


def test_import_api_platform_uses_title(demo_video, monkeypatch):
    from app.main import app

    def fake_download(url, stem, limit, progress=None):
        dest = stem.with_suffix(".mp4")
        shutil.copy(demo_video, dest)
        if progress:
            progress(1.0)
        return dest, "Insane GTA 6 police chase | Stream #42"

    monkeypatch.setattr(importer, "download_platform", fake_download)
    with TestClient(app) as client:
        r = client.post("/api/videos/import", json={"url": "https://www.twitch.tv/videos/1", "max_clips": 2})
        video = _wait(client, f"/api/videos/{r.json()['id']}")
        assert video["status"] == "ready", video["error"]
        assert video["name"] == "Insane GTA 6 police chase | Stream #42.mp4"
        assert video["import_url"] == "https://www.twitch.tv/videos/1"


def test_dns_rebinding_is_blocked_at_connect_time(monkeypatch, tmp_path):
    """First lookup says public, the next says loopback: the connection must be refused."""
    import socket as _socket

    monkeypatch.delenv("CLIPWIZARD_ALLOW_PRIVATE_URLS", raising=False)
    monkeypatch.delenv("CLIPWIZARD_IMPORT_USE_PROXY", raising=False)
    real = _socket.getaddrinfo
    calls = {"n": 0}

    def flaky(host, port, *a, **k):
        if host == "rebind.example":
            calls["n"] += 1
            ip = "93.184.216.34" if calls["n"] == 1 else "127.0.0.1"
            return [(_socket.AF_INET, _socket.SOCK_STREAM, 6, "", (ip, port))]
        return real(host, port, *a, **k)

    monkeypatch.setattr(_socket, "getaddrinfo", flaky)
    with pytest.raises(importer.ImportFailed, match="private"):
        importer.download_direct("http://rebind.example/v.mp4", tmp_path / "x.mp4", 2**20)
    assert calls["n"] >= 2


@pytest.mark.parametrize("addr", ["::ffff:127.0.0.1", "::127.0.0.1", "64:ff9b::a00:1", "100.64.0.1", "0.0.0.0"])
def test_embedded_private_addresses(addr):
    import ipaddress

    assert not importer._is_public(ipaddress.ip_address(addr))


def test_public_addresses_allowed():
    import ipaddress

    assert importer._is_public(ipaddress.ip_address("93.184.216.34"))
    assert importer._is_public(ipaddress.ip_address("2606:2800:220:1:248:1893:25c8:1946"))
