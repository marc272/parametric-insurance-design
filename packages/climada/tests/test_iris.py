"""Tests for the IRIS download, extract and merge (MAR-72).

CI never downloads IRIS. These tests build a synthetic mini event set in a
temporary directory (ten tiny NA files in a zip, plus a matching manifest)
and serve it through an injected opener that counts requests.
"""

from __future__ import annotations

import hashlib
import io
import json
import zipfile
from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import replace
from pathlib import Path
from typing import IO

import pytest

from parametric_insurance_design_climada import iris

HEADER = b"#tcid basin year tc month timestep lon lat vmax pmin rmw r18\n"

# Merged checksum of the thesis file IRIS_NA_10000Y_merged.txt (MAR-72 PR).
THESIS_MERGED_SHA256 = (
    "7f7b224d87db743b5653ebfaa8d9ed1e9e8e7cffc1483643fc9a085f155606bd"
)


def _member_bytes(k: int) -> bytes:
    """A tiny IRIS-like file: header plus two rows per year, years k*2..k*2+1."""
    rows = [HEADER]
    for year in (2 * k, 2 * k + 1):
        tcid = 10 * k + year
        rows.append(
            f"{tcid} NA {year} 0 8 0 -54.9 20.3 60.2 931.0 24.0 322.1\n".encode()
        )
        rows.append(
            f"{tcid} NA {year} 0 8 1 -55.6 20.9 58.8 933.9 25.2 316.7\n".encode()
        )
    return b"".join(rows)


def _expected(name: str, data: bytes) -> dict[str, object]:
    return {
        "name": name,
        "size": len(data),
        "lines": data.count(b"\n"),
        "sha256": hashlib.sha256(data).hexdigest(),
    }


def _remote(name: str, data: bytes, url: str) -> dict[str, object]:
    raw = _expected(name, data)
    raw.update(
        url=url,
        doi="10.0/test",
        md5=hashlib.md5(data, usedforsecurity=False).hexdigest(),
    )
    return raw


class FakeHost:
    """Serves bytes by URL and counts requests."""

    def __init__(self, content: dict[str, bytes]) -> None:
        self.content = content
        self.calls: list[str] = []

    def __call__(self, url: str) -> AbstractContextManager[IO[bytes]]:
        self.calls.append(url)
        return io.BytesIO(self.content[url])


Mini = tuple[iris.IrisManifest, FakeHost, bytes, Path]


@pytest.fixture
def mini(tmp_path: Path) -> Mini:
    """A synthetic IRIS: manifest, host, expected merged bytes, manifest path."""
    members = {f"IRIS_NA_1000Y_n{k}.txt": _member_bytes(k) for k in range(10)}
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        # Other basins and reverse order, so extraction must pick by name.
        zf.writestr("IRIS_EP_1000Y_n0.txt", HEADER + b"0 EP 0 0 8 0 1 1 1 1 1 1\n")
        for name in sorted(members, reverse=True):
            zf.writestr(name, members[name])
    archive = buf.getvalue()
    readme = b"IRIS - Imperial College Storm Model - Event set description\r\n"
    merged = HEADER + b"".join(
        members[f"IRIS_NA_1000Y_n{k}.txt"][len(HEADER) :] for k in range(10)
    )
    raw = {
        "dataset": "mini IRIS",
        "version": "test",
        "collection_doi": "10.0/c",
        "article_doi": "10.0/a",
        "licence": "CC0-1.0 on one record, CC-BY-4.0 on another",
        "licence_applied": "CC-BY-4.0",
        "licence_resolution": "test",
        "citation": "test",
        "archive": _remote("IRIS_event_set.zip", archive, "https://host/zip"),
        "readme": _remote("IRIS_event_set_README.txt", readme, "https://host/readme"),
        "basin": "NA",
        "members": [
            _expected(f"IRIS_NA_1000Y_n{k}.txt", members[f"IRIS_NA_1000Y_n{k}.txt"])
            for k in range(10)
        ],
        "merged": _expected("IRIS_NA_10000Y_merged.txt", merged),
    }
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(raw))
    host = FakeHost({"https://host/zip": archive, "https://host/readme": readme})
    return iris.load_manifest(path), host, merged, path


# --- the shipped manifest ----------------------------------------------------


def test_shipped_manifest_pins_the_figshare_files_and_the_thesis_merge() -> None:
    m = iris.load_manifest()
    assert m.archive.url == "https://ndownloader.figshare.com/files/43809540"
    assert m.archive.doi == "10.6084/m9.figshare.24894186.v1"
    assert m.readme.doi == "10.6084/m9.figshare.24894189.v1"
    assert m.collection_doi == "10.6084/m9.figshare.c.6724251.v1"
    assert [x.name for x in m.members] == [f"IRIS_NA_1000Y_n{k}.txt" for k in range(10)]
    assert m.merged.name == "IRIS_NA_10000Y_merged.txt"
    assert m.merged.sha256 == THESIS_MERGED_SHA256
    for f in (m.archive, m.readme, *m.members, m.merged):
        assert len(f.sha256) == 64
        assert int(f.sha256, 16) >= 0


def test_shipped_manifest_applies_the_owner_licence_decision() -> None:
    # MAR-94: both records are kept, and IRIS-derived data is CC BY 4.0.
    m = iris.load_manifest()
    assert m.licence_applied == "CC-BY-4.0"
    assert "CC0-1.0" in m.licence
    assert "CC-BY-4.0" in m.licence
    assert "owner decision" in m.licence_resolution
    assert "docs/data-sources.md" in m.licence_resolution


@pytest.mark.parametrize("key", ["licence_applied", "licence_resolution"])
def test_manifest_requires_the_licence_resolution(
    mini: Mini, tmp_path: Path, key: str
) -> None:
    *_, path = mini
    raw = json.loads(path.read_text())
    del raw[key]
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps(raw))
    with pytest.raises(iris.IrisDataError, match=key):
        iris.load_manifest(bad)


def test_shipped_manifest_is_self_consistent() -> None:
    # Merging drops nine header lines of len(HEADER) bytes each.
    m = iris.load_manifest()
    assert sum(x.size for x in m.members) - 9 * len(HEADER) == m.merged.size
    assert m.merged.lines is not None
    assert sum(x.lines or 0 for x in m.members) - 9 == m.merged.lines


def test_manifest_rejects_members_out_of_order(mini: Mini, tmp_path: Path) -> None:
    *_, path = mini
    raw = json.loads(path.read_text())
    raw["members"] = raw["members"][::-1]
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps(raw))
    with pytest.raises(iris.IrisDataError, match="merge order"):
        iris.load_manifest(bad)


def test_manifest_reports_missing_key(tmp_path: Path) -> None:
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"dataset": "x"}))
    with pytest.raises(iris.IrisDataError, match="missing the key"):
        iris.load_manifest(bad)


# --- ordering ----------------------------------------------------------------


def test_order_members_sorts_numerically_like_the_thesis() -> None:
    names = [f"IRIS_NA_1000Y_n{k}.txt" for k in (3, 0, 9, 1, 2, 8, 4, 7, 5, 6)]
    assert iris.order_members(names) == [f"IRIS_NA_1000Y_n{k}.txt" for k in range(10)]


@pytest.mark.parametrize(
    "names",
    [
        [f"IRIS_NA_1000Y_n{k}.txt" for k in range(9)],
        [*(f"IRIS_NA_1000Y_n{k}.txt" for k in range(9)), "IRIS_NA_1000Y_n0.txt"],
        [*(f"IRIS_NA_1000Y_n{k}.txt" for k in range(9)), "IRIS_EP_1000Y_n9.txt"],
        [*(f"IRIS_NA_1000Y_n{k}.txt" for k in range(9)), "IRIS_NA_1000Y_n9.csv"],
    ],
)
def test_order_members_rejects_incomplete_or_foreign_sets(names: list[str]) -> None:
    with pytest.raises(iris.IrisDataError):
        iris.order_members(names)


# --- merge -------------------------------------------------------------------


def _write(tmp_path: Path, name: str, data: bytes) -> Path:
    p = tmp_path / name
    p.write_bytes(data)
    return p


def _thesis_merge(paths: list[Path], out: Path) -> None:
    """The thesis IRIS_transformer.py merge loop, verbatim in behaviour."""
    with open(out, "w") as out_f:
        for i, f in enumerate(paths):
            with open(f) as in_f:
                for j, line in enumerate(in_f):
                    if i > 0 and j == 0:
                        continue
                    out_f.write(line)


def test_merge_matches_the_thesis_algorithm_byte_for_byte(tmp_path: Path) -> None:
    paths = [
        _write(tmp_path, f"IRIS_NA_1000Y_n{k}.txt", _member_bytes(k)) for k in range(10)
    ]
    ours, theirs = tmp_path / "ours.txt", tmp_path / "theirs.txt"
    lines = iris.merge_track_files(paths, ours)
    _thesis_merge(paths, theirs)
    assert ours.read_bytes() == theirs.read_bytes()
    assert lines == ours.read_bytes().count(b"\n") == 1 + 10 * 4
    assert ours.read_bytes().count(HEADER) == 1
    assert not (tmp_path / "ours.txt.part").exists()


def test_merge_keeps_a_header_only_file(tmp_path: Path) -> None:
    a = _write(tmp_path, "a.txt", _member_bytes(0))
    b = _write(tmp_path, "b.txt", HEADER)
    out = tmp_path / "out.txt"
    assert iris.merge_track_files([a, b], out) == 5
    assert out.read_bytes() == _member_bytes(0)


@pytest.mark.parametrize(
    ("second", "match"),
    [
        (b"0 NA 0 0 8 0 1 1 1 1 1 1\n", "not a '#' header"),
        (b"#tcid basin year\n0 NA 0\n", "differs"),
        (HEADER.replace(b"\n", b"\r\n") + b"0 NA\r\n", "CRLF"),
        (HEADER + b"0 NA 0 0 8 0 1 1 1 1 1 1", "newline"),
        (b"", "not a '#' header"),
    ],
)
def test_merge_refuses_what_the_thesis_silently_assumed(
    tmp_path: Path, second: bytes, match: str
) -> None:
    a = _write(tmp_path, "a.txt", _member_bytes(0))
    b = _write(tmp_path, "b.txt", second)
    out = tmp_path / "out.txt"
    with pytest.raises(iris.MergeFormatError, match=match):
        iris.merge_track_files([a, b], out)
    assert not out.exists()


def test_merge_needs_inputs(tmp_path: Path) -> None:
    with pytest.raises(iris.MergeFormatError, match="no input"):
        iris.merge_track_files([], tmp_path / "out.txt")


def test_merge_with_wrong_expectation_leaves_no_file(tmp_path: Path) -> None:
    a = _write(tmp_path, "a.txt", _member_bytes(0))
    out = tmp_path / "out.txt"
    wrong = iris.ExpectedFile(name="out.txt", size=1, sha256="0" * 64)
    with pytest.raises(iris.ChecksumMismatchError):
        iris.merge_track_files([a], out, expected=wrong)
    assert not out.exists()
    assert not (tmp_path / "out.txt.part").exists()


# --- download ----------------------------------------------------------------


def test_download_verifies_and_is_idempotent(mini: Mini, tmp_path: Path) -> None:
    manifest, host, *_ = mini
    path, created = iris.download_file(manifest.readme, tmp_path / "raw", opener=host)
    assert created
    assert path.read_bytes().startswith(b"IRIS")
    path2, created2 = iris.download_file(manifest.readme, tmp_path / "raw", opener=host)
    assert (path2, created2) == (path, False)
    assert host.calls == ["https://host/readme"]


def test_download_with_bad_bytes_leaves_nothing(mini: Mini, tmp_path: Path) -> None:
    manifest, _, *_ = mini
    corrupt = FakeHost({"https://host/readme": b"truncated"})
    with pytest.raises(iris.ChecksumMismatchError, match="size"):
        iris.download_file(manifest.readme, tmp_path / "raw", opener=corrupt)
    assert list((tmp_path / "raw").iterdir()) == []


def test_download_checks_md5_as_well(mini: Mini, tmp_path: Path) -> None:
    manifest, host, *_ = mini
    wrong_md5 = replace(manifest.readme, md5="0" * 32)
    with pytest.raises(iris.ChecksumMismatchError, match="md5"):
        iris.download_file(wrong_md5, tmp_path, opener=host)


def test_existing_mismatching_file_is_kept_and_reported(
    mini: Mini, tmp_path: Path
) -> None:
    manifest, host, *_ = mini
    existing = _write(tmp_path, manifest.readme.name, b"someone else's file")
    with pytest.raises(iris.ChecksumMismatchError, match="left untouched"):
        iris.download_file(manifest.readme, tmp_path, opener=host)
    assert existing.read_bytes() == b"someone else's file"
    assert host.calls == []


def test_default_opener_refuses_non_https(mini: Mini, tmp_path: Path) -> None:
    manifest, *_ = mini
    plain = replace(manifest.readme, url="http://host/readme")
    with pytest.raises(iris.IrisDataError, match="non-https"):
        iris.download_file(plain, tmp_path)


# --- extract and the whole pipeline ------------------------------------------


def test_extract_reports_a_missing_member(mini: Mini, tmp_path: Path) -> None:
    manifest, host, *_ = mini
    archive, _ = iris.download_file(manifest.archive, tmp_path, opener=host)
    ghost = iris.ExpectedFile(name="IRIS_NA_1000Y_n42.txt", size=1, sha256="0" * 64)
    with pytest.raises(iris.IrisDataError, match="no member"):
        iris.extract_members(archive, [ghost], tmp_path / "x")


def test_prepare_iris_end_to_end_then_idempotent(mini: Mini, tmp_path: Path) -> None:
    manifest, host, merged, _ = mini
    data = tmp_path / "data"
    first = iris.prepare_iris(data, manifest=manifest, opener=host)
    assert first.merged == data / "transformed" / "IRIS_NA_10000Y_merged.txt"
    assert first.merged.read_bytes() == merged
    assert set(first.actions.values()) == {"created"}
    assert len(first.actions) == 13  # zip, README, 10 members, merged
    # Only the NA members were extracted; nothing else from the zip.
    extracted = sorted(p.name for p in (data / "raw" / "IRIS_event_set").iterdir())
    assert extracted == [f"IRIS_NA_1000Y_n{k}.txt" for k in range(10)]
    assert not list(data.rglob("*.part"))

    second = iris.prepare_iris(data, manifest=manifest, opener=host)
    assert set(second.actions.values()) == {"verified"}
    assert host.calls == ["https://host/zip", "https://host/readme"]
    assert second.merged.read_bytes() == merged


def test_prepare_iris_rebuilds_a_missing_merge_only(mini: Mini, tmp_path: Path) -> None:
    manifest, host, merged, _ = mini
    data = tmp_path / "data"
    first = iris.prepare_iris(data, manifest=manifest, opener=host)
    first.merged.unlink()
    second = iris.prepare_iris(data, manifest=manifest, opener=host)
    assert second.actions[manifest.merged.name] == "created"
    assert second.actions[manifest.archive.name] == "verified"
    assert second.merged.read_bytes() == merged


def test_prepare_iris_uses_a_local_archive_without_downloading_it(
    mini: Mini, tmp_path: Path
) -> None:
    manifest, host, merged, _ = mini
    local = tmp_path / "elsewhere" / "IRIS_event_set.zip"
    local.parent.mkdir()
    local.write_bytes(host.content["https://host/zip"])
    data = tmp_path / "data"
    paths = iris.prepare_iris(data, manifest=manifest, archive=local, opener=host)
    assert paths.archive == local
    assert host.calls == ["https://host/readme"]
    assert not (data / "raw" / "IRIS_event_set.zip").exists()
    assert paths.merged.read_bytes() == merged


def test_prepare_iris_rejects_a_bad_local_archive(mini: Mini, tmp_path: Path) -> None:
    manifest, host, *_ = mini
    local = _write(tmp_path, "IRIS_event_set.zip", b"not a zip")
    with pytest.raises(iris.ChecksumMismatchError):
        iris.prepare_iris(tmp_path / "d", manifest=manifest, archive=local, opener=host)


# --- command line ------------------------------------------------------------


def _patch_pipeline(
    monkeypatch: pytest.MonkeyPatch,
    manifest: iris.IrisManifest,
    host: Callable[[str], AbstractContextManager[IO[bytes]]],
) -> None:
    real = iris.prepare_iris
    monkeypatch.setattr(iris, "load_manifest", lambda path=None: manifest)
    monkeypatch.setattr(
        iris,
        "prepare_iris",
        lambda data_dir, **kw: real(data_dir, **{**kw, "opener": host}),
    )


def test_main_runs_and_reports(
    mini: Mini,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    manifest, host, *_ = mini
    _patch_pipeline(monkeypatch, manifest, host)
    assert iris.main(["--data-dir", str(tmp_path / "d")]) == 0
    out = capsys.readouterr().out
    assert "created   IRIS_NA_10000Y_merged.txt" in out
    assert manifest.merged.sha256 in out
    assert "licence: CC-BY-4.0 (test)" in out


def test_main_returns_1_on_a_data_error(
    mini: Mini,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    manifest, *_ = mini
    _patch_pipeline(monkeypatch, manifest, FakeHost({"https://host/zip": b"x"}))
    assert iris.main(["--data-dir", str(tmp_path / "d")]) == 1
    assert "error:" in capsys.readouterr().err
