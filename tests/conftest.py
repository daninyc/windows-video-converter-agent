import ipaddress
import socket
from pathlib import Path

import pytest


def pytest_configure(config):
    Path(config.option.basetemp).resolve().parent.mkdir(parents=True, exist_ok=True)


def pytest_addoption(parser):
    parser.addoption("--data-dir", default="artifacts/test-data", help="独立应用测试数据目录")
    parser.addoption("--fixture-root", default="artifacts/fixtures", help="生成素材目录")
    parser.addoption(
        "--xiph-root", type=Path, help="显式启用已下载的 Xiph 真实素材测试；不联网下载"
    )
    parser.addoption("--live-api", action="store_true", help="显式允许真实在线 API 测试")


def pytest_collection_modifyitems(config, items):
    if not config.getoption("--live-api"):
        for item in items:
            if "live_api" in item.keywords:
                item.add_marker(pytest.mark.skip(reason="需要显式 --live-api"))


@pytest.fixture(autouse=True)
def prevent_unrequested_online_requests(request, monkeypatch):
    if request.config.getoption("--live-api"):
        return
    original_connect = socket.socket.connect
    original_connect_ex = socket.socket.connect_ex
    original_resolve = socket.getaddrinfo

    def check(host):
        if host in ("localhost", b"localhost"):
            return
        try:
            if ipaddress.ip_address(host).is_loopback:
                return
        except ValueError:
            pass
        raise RuntimeError("在线网络访问默认禁止；真实 API 测试须显式 --live-api")

    def connect(sock, address):
        if sock.family in (socket.AF_INET, socket.AF_INET6):
            check(address[0])
        return original_connect(sock, address)

    def connect_ex(sock, address):
        check(address[0])
        return original_connect_ex(sock, address)

    def resolve(host, *args, **kwargs):
        if host is not None:
            check(host)
        return original_resolve(host, *args, **kwargs)

    monkeypatch.setattr(socket.socket, "connect", connect)
    monkeypatch.setattr(socket.socket, "connect_ex", connect_ex)
    monkeypatch.setattr(socket, "getaddrinfo", resolve)


@pytest.fixture
def data_dir(request, tmp_path):
    root = Path(request.config.getoption("--data-dir")).resolve()
    root.mkdir(parents=True, exist_ok=True)
    return root / tmp_path.name


@pytest.fixture
def fixture_root(request):
    return Path(request.config.getoption("--fixture-root")).resolve()


@pytest.fixture(scope="session")
def ai_source(request):
    root = Path(request.config.getoption("--data-dir")).resolve()
    if not (root / "ai-components.json").is_file():
        pytest.skip("本地 AI 组件未配置；真实本地验收须 --data-dir data")
    return root
