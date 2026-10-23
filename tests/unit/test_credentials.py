import pytest

from media_converter.common.errors import AppError
from media_converter.services.config import APIConfig, ConfigService

pytestmark = pytest.mark.unit


def test_dpapi_restore_replace_and_revoke_without_plaintext(tmp_path):
    service = ConfigService(tmp_path)
    sentinel = "sentinel-key-never-public"
    saved = service.save(APIConfig(), sentinel)
    assert sentinel not in service.path.read_text(encoding="utf-8")
    assert sentinel.encode() not in service.credentials._path(saved.credential_ref).read_bytes()
    assert ConfigService(tmp_path).request_config()[1] == sentinel
    old = saved.credential_ref
    saved = service.save(saved, "replacement")
    assert not service.credentials._path(old).exists()
    service.save(saved, clear=True)
    with pytest.raises(AppError):
        service.request_config()


def test_endpoint_rejects_embedded_credentials_and_insecure_remote():
    for url in ["https://key@example.com", "http://example.com", "https://example.com/?key=secret"]:
        with pytest.raises(ValueError):
            APIConfig(base_url=url)
