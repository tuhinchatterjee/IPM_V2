"""What a Brain package may contain, and what it may never. §10, §26, §49.

Every test here is an attack or a leak. A Brain Pack arrives from another
installation and a person is about to click Import; these are the reasons
that click cannot hurt them.
"""

from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path

import pytest

from backend.brain import pack, security


@pytest.fixture
def manifest():
    return pack.Manifest(
        brain_id="brain-test-1",
        brain_name="Test Brain",
        brain_version="1.0.0",
        created_by="tests",
        source_instance_id="instance-a",
        source_build_sha="abc1234",
        app_version="2026.8.0",
        minimum_app_version="2026.8.0",
        ontology_version="2.0.0",
    )


@pytest.fixture
def contents():
    body = pack.Contents()
    body.add("ontology/concepts.json", {"version": "2.0.0", "concepts": []})
    body.add_jsonl("teaching/cases.jsonl",
                   [{"case_id": "T-1", "question": "What is ECL by sector?"}])
    body.add("evaluations/summary.json", {"development": {"score": 0.82}})
    return body


def _zip(entries: dict[str, bytes], **kwargs) -> bytes:
    """A package built by hand, for the attacks.

    `compress_type` is set on each entry explicitly: a bare `ZipInfo`
    defaults to STORED whatever the archive's mode, and the first version of
    this helper wrote an uncompressed 2 MB "bomb" that the detector
    correctly declined to call one.
    """
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, body in entries.items():
            info = zipfile.ZipInfo(name)
            info.compress_type = zipfile.ZIP_DEFLATED
            for key, value in kwargs.get(name, {}).items():
                setattr(info, key, value)
            archive.writestr(info, body)
    return buffer.getvalue()


# ============================================================ path safety


@pytest.mark.parametrize("name", [
    "../../etc/passwd",
    "..\\..\\windows\\system32\\x",
    "/etc/passwd",
    "C:/windows/x",
    "teaching/../../../x.json",
])
def test_a_path_that_escapes_the_package_root_is_refused(name):
    """Zip-slip: the archive path is attacker-controlled."""
    assert security.unsafe_path(name), name


@pytest.mark.parametrize("name", [
    "manifest.json", "teaching/cases.jsonl", "ontology/concepts.json",
])
def test_an_ordinary_path_is_allowed(name):
    assert security.unsafe_path(name) == ""


def test_a_null_byte_in_a_path_is_refused():
    assert security.unsafe_path("teaching/a\x00b.json")


def test_zip_slip_is_caught_by_inspection():
    raw = _zip({"../../evil.json": b"{}"})
    report = security.inspect("evil.cpbrain", raw)
    assert not report.clean
    assert any(p.kind == "path" for p in report.blocking)


def test_a_symlink_entry_is_refused():
    """A symlink writes wherever it points when extracted."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        info = zipfile.ZipInfo("teaching/link.json")
        info.external_attr = (0o120777 << 16)
        archive.writestr(info, "/etc/passwd")
    report = security.inspect("x.cpbrain", buffer.getvalue())
    assert not report.clean
    assert any("symlink" in p.detail for p in report.blocking)


# ======================================================== forbidden formats


@pytest.mark.parametrize("name,expected", [
    ("auxiliary_models/model.pkl", "pickle"),
    ("auxiliary_models/model.joblib", "joblib"),
    ("auxiliary_models/model.pt", "torch"),
    ("scripts/install.sh", "shell"),
    ("scripts/run.ps1", "PowerShell"),
    ("code/handler.py", "Python"),
    ("data/dump.sql", "SQL"),
    ("data/portfolio.db", "database"),
    ("book.xlsm", "macro"),
])
def test_an_executable_or_dump_format_is_refused(name, expected):
    raw = _zip({name: b"anything"})
    report = security.inspect("x.cpbrain", raw)
    assert not report.clean
    assert any(expected.lower() in p.detail.lower()
               for p in report.blocking), [p.detail for p in report.blocking]


def test_a_dotenv_is_refused_by_name():
    raw = _zip({".env": b"ANTHROPIC_API_KEY=x"})
    report = security.inspect("x.cpbrain", raw)
    assert not report.clean


def test_the_allowlist_is_an_allowlist_not_a_blocklist():
    """An unknown format is refused, not permitted by omission."""
    raw = _zip({"teaching/cases.weird": b"{}"})
    report = security.inspect("x.cpbrain", raw)
    assert not report.clean
    assert any("allowlist" in p.detail for p in report.blocking)


def test_onnx_is_allowed_because_it_is_data():
    assert ".onnx" in security.ALLOWED_SUFFIXES
    assert ".pkl" not in security.ALLOWED_SUFFIXES


# ======================================================= decompression bomb


def test_a_decompression_bomb_is_refused_from_its_directory_entry():
    """Refused from the metadata, before a byte is decompressed."""
    raw = _zip({"teaching/cases.jsonl": b"A" * (2 * 1024 * 1024)})
    report = security.inspect("bomb.cpbrain", raw)
    assert not report.clean
    assert any(p.kind == "bomb" for p in report.blocking)


def test_ordinary_text_compression_is_not_mistaken_for_a_bomb():
    """A real corpus compresses well. The bar has to clear that."""
    rows = [json.dumps({"case_id": f"T-{i}",
                        "question": f"What is ECL for sector {i}?",
                        "expected": "a grouped total"})
            for i in range(2000)]
    raw = _zip({"teaching/cases.jsonl": "\n".join(rows).encode()})
    report = security.inspect("real.cpbrain", raw)
    assert not [p for p in report.blocking if p.kind == "bomb"]


# ============================================================== the leaks


@pytest.mark.parametrize("secret", [
    "sk-ant-api03-AAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
    "AKIAIOSFODNN7EXAMPLE",
    "-----BEGIN RSA PRIVATE KEY-----",
    "postgresql://user:hunter2@db:5432/creditprobe",
    'api_key: "abcdef0123456789abcdef"',
])
def test_a_secret_in_a_package_is_refused(secret):
    raw = _zip({"prompts/system.md": secret.encode()})
    report = security.inspect("x.cpbrain", raw)
    assert not report.clean
    assert any(p.kind == "secret" for p in report.blocking)


def test_a_secret_is_never_echoed_back():
    """Reporting a leak must not repeat it into a log or a screen."""
    key = "sk-ant-api03-SUPERSECRETVALUE0000000000"
    found = security.scan_secrets(key)
    assert found
    for _label, shown in found:
        assert key not in shown
        assert shown.endswith("chars)")


def test_client_rows_in_a_package_are_refused():
    rows = json.dumps([{"customer_id": "C-001", "borrower_name": "Acme"}])
    raw = _zip({"teaching/cases.jsonl": rows.encode()})
    report = security.inspect("x.cpbrain", raw)
    assert not report.clean
    assert any(p.kind == "client_data" for p in report.blocking)


# ============================================================= signatures


def test_an_unsigned_package_may_be_inspected_but_is_flagged(tmp_path,
                                                             manifest,
                                                             contents):
    """§26: inspect and evaluate freely; activation needs approval."""
    target = pack.write(tmp_path / "b.cpbrain", manifest, contents)
    report = security.inspect(str(target))
    assert report.clean, [p.detail for p in report.blocking]
    assert report.signature_state == "UNSIGNED"
    assert any(p.kind == "signature" and not p.blocking
               for p in report.problems)


def test_a_trusted_signature_verifies(tmp_path, manifest, contents):
    key = b"a shared signing key"
    target = pack.write(tmp_path / "b.cpbrain", manifest, contents,
                        signing_key=key, signing_key_id="riyadh")
    report = security.inspect(str(target),
                              trusted_keys={"riyadh": key})
    assert report.signature_state == "TRUSTED"
    assert report.clean


def test_an_untrusted_signer_is_reported_and_not_blocked(tmp_path, manifest,
                                                         contents):
    target = pack.write(tmp_path / "b.cpbrain", manifest, contents,
                        signing_key=b"k", signing_key_id="stranger")
    report = security.inspect(str(target), trusted_keys={})
    assert report.signature_state == "UNTRUSTED_SIGNER"
    assert report.clean, "an untrusted package may still be evaluated"


def test_a_tampered_package_fails_its_signature(tmp_path, manifest,
                                                contents):
    key = b"a shared signing key"
    target = pack.write(tmp_path / "b.cpbrain", manifest, contents,
                        signing_key=key, signing_key_id="riyadh")
    raw = bytearray(target.read_bytes())
    with zipfile.ZipFile(io.BytesIO(bytes(raw))) as archive:
        files = {n: archive.read(n) for n in archive.namelist()}
    files["ontology/concepts.json"] = b'{"version": "9.9.9"}'
    tampered = _zip(files)
    report = security.inspect("tampered.cpbrain", tampered,
                              trusted_keys={"riyadh": key})
    assert report.signature_state in ("CONTENT_CHANGED", "INVALID")
    assert not report.clean


# ============================================================== the manifest


def test_a_manifest_missing_what_it_is_cannot_be_written(tmp_path, contents):
    empty = pack.Manifest(brain_id="", brain_name="", brain_version="")
    with pytest.raises(pack.PackError):
        pack.write(tmp_path / "x.cpbrain", empty, contents)


def test_the_manifest_carries_no_secret_field():
    fields = set(pack.Manifest.__dataclass_fields__)
    assert not fields & pack.FORBIDDEN_MANIFEST_KEYS


def test_a_manifest_may_not_carry_a_tenant_id():
    """§11: a redacted organisation identifier, never a tenant."""
    assert "source_tenant_id" in pack.FORBIDDEN_MANIFEST_KEYS
    assert "source_organization" in pack.Manifest.__dataclass_fields__


def test_a_manifest_cannot_claim_more_approved_cases_than_it_holds(manifest):
    manifest.case_counts = {"AUTO_VALIDATED": 10}
    manifest.human_approved_count = 40
    problems = pack.validate_manifest(manifest)
    assert any("cannot both be true" in p for p in problems)


def test_client_derived_patterns_must_declare_redaction(manifest):
    manifest.contains_client_derived_patterns = True
    manifest.redaction_status = "NONE"
    assert any("redacted" in p for p in pack.validate_manifest(manifest))


# ========================================= what may not leave, on the way out


def test_a_package_that_could_not_be_imported_cannot_be_exported(tmp_path,
                                                                 manifest):
    """The check runs on export as well as import.

    The first installation to trust its own export is the one that ships
    the problem.
    """
    leaky = pack.Contents()
    leaky.add("prompts/system.md",
              "sk-ant-api03-AAAAAAAAAAAAAAAAAAAAAAAAAAAA")
    with pytest.raises(pack.PackError, match="secret|API key"):
        pack.write(tmp_path / "x.cpbrain", manifest, leaky)


def test_the_sealed_holdout_may_never_be_packaged(tmp_path, manifest):
    sealed = pack.Contents()
    sealed.add_jsonl("teaching/holdout/cases.jsonl", [{"case_id": "HO-1"}])
    with pytest.raises(pack.PackError, match="sealed holdout"):
        pack.write(tmp_path / "x.cpbrain", manifest, sealed)


def test_raw_feedback_may_never_be_packaged(tmp_path, manifest):
    raw = pack.Contents()
    raw.add_jsonl("feedback/raw/events.jsonl", [{"rating": "bad"}])
    with pytest.raises(pack.PackError):
        pack.write(tmp_path / "x.cpbrain", manifest, raw)


def test_an_unknown_top_level_directory_is_refused(tmp_path, manifest):
    odd = pack.Contents()
    odd.add("mystery/thing.json", {})
    with pytest.raises(pack.PackError, match="unknown top-level"):
        pack.write(tmp_path / "x.cpbrain", manifest, odd)


# ============================================================ round tripping


def test_a_written_package_reads_back(tmp_path, manifest, contents):
    target = pack.write(tmp_path / "b.cpbrain", manifest, contents)
    opened = pack.read(target)
    assert opened.usable, opened.problems
    assert opened.manifest.brain_id == "brain-test-1"
    assert "teaching/cases.jsonl" in opened.files
    assert "README.md" in opened.files


def test_the_readme_says_what_the_package_is_not(tmp_path, manifest,
                                                 contents):
    target = pack.write(tmp_path / "b.cpbrain", manifest, contents)
    readme = pack.read(target).files["README.md"]
    assert "Not Claude foundation-model weights" in readme
    assert "Not credentials" in readme
    assert "Not client data" in readme
    assert "Not a sealed holdout" in readme


def test_content_hashes_catch_a_swapped_entry(tmp_path, manifest, contents):
    target = pack.write(tmp_path / "b.cpbrain", manifest, contents)
    with zipfile.ZipFile(io.BytesIO(target.read_bytes())) as archive:
        files = {n: archive.read(n) for n in archive.namelist()}
    files["ontology/concepts.json"] = b'{"version": "impostor"}'
    Path(tmp_path / "swapped.cpbrain").write_bytes(_zip(files))
    opened = pack.read(tmp_path / "swapped.cpbrain")
    assert not opened.usable
    assert any("altered since it was built" in p for p in opened.problems)


def test_every_package_kind_has_a_suffix():
    for kind in (pack.BRAIN_PACK, pack.LEARNING_BUNDLE,
                 pack.DEVELOPER_BUNDLE):
        assert pack.SUFFIX[kind].startswith(".")
