"""Download and merge the IRIS North Atlantic event set, with checksums.

IRIS (the Imperial College Storm Model; Sparks and Toumi, 2024) publishes a
10,000-year synthetic tropical cyclone event set on figshare as one zip
archive, with ten 1,000-year text files per basin. This module replaces the
thesis script ``scripts/IRIS_transformer.py``:

1. download the archive and its README from figshare, checking size, MD5 and
   SHA256 (:func:`download_file`);
2. extract the ten North Atlantic files, checking each one's SHA256
   (:func:`extract_members`);
3. merge them into one 10,000-year catalogue as the thesis did
   (:func:`merge_track_files`), and check the result's SHA256.

Every expected size and checksum is pinned in the manifest shipped with this
package (``iris_manifest.json``, read by :func:`load_manifest`). Each step is
idempotent: a file that is already present and matches the manifest is kept
and not fetched or rebuilt again. A file that is present but does not match
raises :class:`ChecksumMismatchError`; it is never overwritten or deleted.
Files are written to ``<name>.part`` first and renamed only once verified, so
an interrupted run never leaves a final file that has not been checked.

Layout under ``data_dir`` (the thesis layout)::

    raw/IRIS_event_set.zip
    raw/IRIS_event_set_README.txt
    raw/IRIS_event_set/IRIS_NA_1000Y_n0.txt ... n9.txt
    transformed/IRIS_NA_10000Y_merged.txt

Run it with ``pixi run iris`` from ``packages/climada`` (writes to the
git-ignored ``data/iris/`` at the repository root), or
``python -m parametric_insurance_design_climada.iris --help``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import re
import shutil
import sys
import urllib.request
import zipfile
from collections.abc import Callable, Sequence
from contextlib import AbstractContextManager
from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path
from typing import IO, Any

__all__ = [
    "ChecksumMismatchError",
    "ExpectedFile",
    "IrisDataError",
    "IrisManifest",
    "IrisPaths",
    "MergeFormatError",
    "RemoteFile",
    "download_file",
    "extract_members",
    "file_digests",
    "load_manifest",
    "main",
    "merge_track_files",
    "order_members",
    "prepare_iris",
    "verify_file",
]

logger = logging.getLogger(__name__)

MANIFEST_RESOURCE = "iris_manifest.json"
USER_AGENT = "parametric-insurance-design-climada (IRIS download; MAR-72)"
_CHUNK = 1 << 20
_MEMBER_INDEX = re.compile(r"_1000Y_n(\d+)\.txt$")

Opener = Callable[[str], AbstractContextManager[IO[bytes]]]
"""Opens a URL for reading bytes. Injected in tests; defaults to urllib."""


class IrisDataError(Exception):
    """Base class for errors while acquiring or merging IRIS data."""


class ChecksumMismatchError(IrisDataError):
    """A file's size or checksum differs from the manifest."""


class MergeFormatError(IrisDataError):
    """An input file does not have the layout the thesis merge assumes."""


@dataclass(frozen=True)
class ExpectedFile:
    """A file with a pinned size and SHA256.

    Attributes
    ----------
    name : str
        File name, without directories.
    size : int
        Size in bytes.
    sha256 : str
        Lower-case hex SHA256 of the file's bytes.
    lines : int or None
        Number of newline characters, if pinned (text files only).
    """

    name: str
    size: int
    sha256: str
    lines: int | None = None


@dataclass(frozen=True)
class RemoteFile(ExpectedFile):
    """A file to download, with its source and the checksum the host states.

    Attributes
    ----------
    url : str
        Download URL.
    doi : str
        DOI of the figshare item that holds the file.
    md5 : str
        MD5 the host (figshare) states for the file, checked as well.
    """

    url: str = ""
    doi: str = ""
    md5: str = ""


@dataclass(frozen=True)
class IrisManifest:
    """Source, licence and pinned checksums of the IRIS files this module uses.

    Attributes
    ----------
    dataset, version, collection_doi, article_doi, licence, citation : str
        Provenance, as recorded in ``docs/data-sources.md``.
    archive : RemoteFile
        The figshare zip with all basins.
    readme : RemoteFile
        The figshare file descriptor (column definitions).
    basin : str
        Basin of ``members`` (``"NA"``).
    members : tuple of ExpectedFile
        The ten 1,000-year files, in merge order (n0 to n9).
    merged : ExpectedFile
        The merged 10,000-year catalogue.
    """

    dataset: str
    version: str
    collection_doi: str
    article_doi: str
    licence: str
    citation: str
    archive: RemoteFile
    readme: RemoteFile
    basin: str
    members: tuple[ExpectedFile, ...]
    merged: ExpectedFile


@dataclass(frozen=True)
class IrisPaths:
    """Where :func:`prepare_iris` put each file, and what it had to do.

    Attributes
    ----------
    archive, readme : Path
        The downloaded zip and README.
    members : tuple of Path
        The extracted 1,000-year files, in merge order.
    merged : Path
        The merged catalogue.
    actions : dict of str to str
        For each file name, ``"created"`` or ``"verified"`` (already present
        and matching the manifest, so left as it was).
    """

    archive: Path
    readme: Path
    members: tuple[Path, ...]
    merged: Path
    actions: dict[str, str]


# --- manifest ---------------------------------------------------------------


def _expected(raw: dict[str, Any]) -> ExpectedFile:
    return ExpectedFile(
        name=str(raw["name"]),
        size=int(raw["size"]),
        sha256=str(raw["sha256"]).lower(),
        lines=None if raw.get("lines") is None else int(raw["lines"]),
    )


def _remote(raw: dict[str, Any]) -> RemoteFile:
    base = _expected(raw)
    return RemoteFile(
        name=base.name,
        size=base.size,
        sha256=base.sha256,
        lines=base.lines,
        url=str(raw["url"]),
        doi=str(raw["doi"]),
        md5=str(raw["md5"]).lower(),
    )


def load_manifest(path: Path | None = None) -> IrisManifest:
    """Read an IRIS manifest.

    Parameters
    ----------
    path : Path, optional
        A manifest JSON file. Defaults to the one shipped with this package.

    Returns
    -------
    IrisManifest
        The parsed manifest. Members are returned in merge order.

    Raises
    ------
    IrisDataError
        If a required key is missing or the member names are not n0 to n9
        of one basin, each exactly once.
    """
    if path is None:
        text = files(__package__ or "parametric_insurance_design_climada")
        raw = json.loads(text.joinpath(MANIFEST_RESOURCE).read_text("utf-8"))
    else:
        raw = json.loads(Path(path).read_text("utf-8"))
    try:
        members = tuple(_expected(m) for m in raw["members"])
        manifest = IrisManifest(
            dataset=str(raw["dataset"]),
            version=str(raw["version"]),
            collection_doi=str(raw["collection_doi"]),
            article_doi=str(raw["article_doi"]),
            licence=str(raw["licence"]),
            citation=str(raw["citation"]),
            archive=_remote(raw["archive"]),
            readme=_remote(raw["readme"]),
            basin=str(raw["basin"]),
            members=members,
            merged=_expected(raw["merged"]),
        )
    except KeyError as exc:
        raise IrisDataError(f"IRIS manifest is missing the key {exc}") from exc
    ordered = order_members([m.name for m in members], basin=manifest.basin)
    if ordered != [m.name for m in members]:
        raise IrisDataError(
            f"IRIS manifest members are not in merge order (n0 to n9): {ordered}"
        )
    return manifest


# --- checksums --------------------------------------------------------------


def file_digests(path: Path) -> tuple[int, str, str]:
    """Return the size, SHA256 and MD5 of a file, read in chunks.

    Parameters
    ----------
    path : Path
        The file.

    Returns
    -------
    tuple of (int, str, str)
        Size in bytes, lower-case hex SHA256 and MD5.
    """
    sha, md5, size = hashlib.sha256(), hashlib.md5(usedforsecurity=False), 0
    with Path(path).open("rb") as fh:
        while chunk := fh.read(_CHUNK):
            sha.update(chunk)
            md5.update(chunk)
            size += len(chunk)
    return size, sha.hexdigest(), md5.hexdigest()


def verify_file(path: Path, expected: ExpectedFile) -> None:
    """Check a file's size and SHA256 (and MD5, for a :class:`RemoteFile`).

    Parameters
    ----------
    path : Path
        The file to check.
    expected : ExpectedFile
        Its pinned size and checksums.

    Raises
    ------
    FileNotFoundError
        If the file does not exist.
    ChecksumMismatchError
        If the size or a checksum differs.
    """
    size, sha256, md5 = file_digests(path)
    problems = []
    if size != expected.size:
        problems.append(f"size {size} != expected {expected.size}")
    if sha256 != expected.sha256:
        problems.append(f"sha256 {sha256} != expected {expected.sha256}")
    if isinstance(expected, RemoteFile) and expected.md5 and md5 != expected.md5:
        problems.append(f"md5 {md5} != expected {expected.md5}")
    if problems:
        raise ChecksumMismatchError(f"{path}: " + "; ".join(problems))


def _already_verified(path: Path, expected: ExpectedFile) -> bool:
    """Return True if ``path`` exists and matches; raise if it exists and not."""
    if not path.exists():
        return False
    try:
        verify_file(path, expected)
    except ChecksumMismatchError as exc:
        raise ChecksumMismatchError(
            f"{exc}. The existing file was left untouched: check it, then move it "
            "away and re-run to fetch or rebuild it."
        ) from exc
    return True


def _finalise(part: Path, final: Path, expected: ExpectedFile) -> None:
    """Verify a ``.part`` file, then rename it to its final name.

    The ``.part`` file is this module's own temporary output, so it is removed
    if it fails verification; the error is raised either way.
    """
    try:
        verify_file(part, expected)
    except ChecksumMismatchError:
        part.unlink()
        raise
    part.replace(final)


# --- download ---------------------------------------------------------------


def _urlopen(url: str) -> AbstractContextManager[IO[bytes]]:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    return urllib.request.urlopen(request, timeout=120)


def download_file(
    remote: RemoteFile, dest_dir: Path, *, opener: Opener | None = None
) -> tuple[Path, bool]:
    """Download a file and verify its size, MD5 and SHA256.

    Parameters
    ----------
    remote : RemoteFile
        What to download and its pinned checksums.
    dest_dir : Path
        Directory to write ``remote.name`` into; created if missing.
    opener : callable, optional
        Opens a URL for reading bytes. Defaults to :mod:`urllib.request`.

    Returns
    -------
    tuple of (Path, bool)
        The verified file, and whether it was downloaded now (False if it was
        already present and verified).

    Raises
    ------
    ChecksumMismatchError
        If the downloaded bytes, or an existing file, do not match.
    IrisDataError
        If the URL is not ``https``.
    """
    dest_dir.mkdir(parents=True, exist_ok=True)
    final = dest_dir / remote.name
    if _already_verified(final, remote):
        logger.info("%s already present and verified", final)
        return final, False
    if opener is None:
        if not remote.url.startswith("https://"):
            raise IrisDataError(f"refusing a non-https download URL: {remote.url}")
        opener = _urlopen
    part = final.with_name(final.name + ".part")
    logger.info("downloading %s (%d bytes) to %s", remote.url, remote.size, final)
    with opener(remote.url) as response, part.open("wb") as out:
        shutil.copyfileobj(response, out, _CHUNK)
    _finalise(part, final, remote)
    return final, True


# --- extract ----------------------------------------------------------------


def extract_members(
    archive: Path, members: Sequence[ExpectedFile], dest_dir: Path
) -> tuple[list[Path], list[bool]]:
    """Extract named files from the IRIS zip and verify each one.

    Only the named members are read, by exact name, so nothing else in the
    archive is written to disk.

    Parameters
    ----------
    archive : Path
        The IRIS zip.
    members : sequence of ExpectedFile
        Files to extract, with their pinned checksums.
    dest_dir : Path
        Directory to extract into; created if missing.

    Returns
    -------
    tuple of (list of Path, list of bool)
        The verified files in the order given, and for each whether it was
        extracted now (False if already present and verified).

    Raises
    ------
    IrisDataError
        If a member is not in the archive.
    ChecksumMismatchError
        If an extracted or existing file does not match.
    """
    dest_dir.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []
    created: list[bool] = []
    with zipfile.ZipFile(archive) as zf:
        names = set(zf.namelist())
        for member in members:
            final = dest_dir / member.name
            paths.append(final)
            if _already_verified(final, member):
                created.append(False)
                continue
            if member.name not in names:
                raise IrisDataError(f"{archive} has no member {member.name!r}")
            part = final.with_name(final.name + ".part")
            with zf.open(member.name) as src, part.open("wb") as out:
                shutil.copyfileobj(src, out, _CHUNK)
            _finalise(part, final, member)
            created.append(True)
    return paths, created


# --- merge ------------------------------------------------------------------


def order_members(names: Sequence[str], *, basin: str = "NA") -> list[str]:
    """Order 1,000-year file names by their index, n0 first, as the thesis did.

    Parameters
    ----------
    names : sequence of str
        File names like ``IRIS_NA_1000Y_n3.txt``.
    basin : str, default "NA"
        The basin every name must belong to.

    Returns
    -------
    list of str
        The names sorted by numeric index.

    Raises
    ------
    IrisDataError
        If a name does not match ``IRIS_<basin>_1000Y_n<k>.txt``, or the
        indices are not exactly 0 to 9.
    """
    keyed: list[tuple[int, str]] = []
    for name in names:
        match = _MEMBER_INDEX.search(name)
        if not name.startswith(f"IRIS_{basin}_1000Y_n") or match is None:
            raise IrisDataError(f"not an IRIS {basin} 1,000-year file name: {name!r}")
        keyed.append((int(match.group(1)), name))
    indices = sorted(k for k, _ in keyed)
    if indices != list(range(10)):
        raise IrisDataError(
            f"expected the indices n0 to n9 once each, got {indices} from {names}"
        )
    return [name for _, name in sorted(keyed)]


def merge_track_files(
    inputs: Sequence[Path], out_path: Path, *, expected: ExpectedFile | None = None
) -> int:
    """Concatenate track files, keeping only the first file's header line.

    This is the thesis merge (``IRIS_transformer.py``): files are written in
    the order given; the first line of the first file is kept, and the first
    line of every later file is dropped. The thesis assumed, without checking,
    that every first line is the same ``#``-prefixed header and that files
    end with a newline; this function checks both and raises otherwise. Bytes
    are copied unchanged, so with LF-terminated inputs (as IRIS ships) the
    output is byte-identical to the thesis output.

    The year column is not rewritten: IRIS years already run 0 to 9,999
    across the ten files (1,000 per file), as its README states.

    Parameters
    ----------
    inputs : sequence of Path
        The files, in merge order.
    out_path : Path
        The merged file. Written to ``<name>.part`` and renamed when done.
    expected : ExpectedFile, optional
        If given, the ``.part`` file is verified against it before the rename,
        so a merged file that does not match never takes the final name.

    Returns
    -------
    int
        Number of lines written, the header included.

    Raises
    ------
    MergeFormatError
        If there are no inputs, a first line is not a ``#`` header, headers
        differ, a header has a carriage return, or a file does not end with a
        newline.
    ChecksumMismatchError
        If ``expected`` is given and the merged bytes do not match it.
    """
    if not inputs:
        raise MergeFormatError("no input files to merge")
    header: bytes | None = None
    for path in inputs:
        with Path(path).open("rb") as fh:
            first = fh.readline()
            if not first.startswith(b"#") or not first.endswith(b"\n"):
                raise MergeFormatError(f"{path}: first line is not a '#' header")
            if b"\r" in first:
                raise MergeFormatError(f"{path}: CRLF line endings are not supported")
            if header is None:
                header = first
            elif first != header:
                raise MergeFormatError(
                    f"{path}: header {first!r} differs from {header!r}"
                )
            fh.seek(0, 2)
            if fh.tell() > len(first):
                fh.seek(-1, 2)
                if fh.read(1) != b"\n":
                    raise MergeFormatError(f"{path}: does not end with a newline")
    assert header is not None

    out_path.parent.mkdir(parents=True, exist_ok=True)
    part = out_path.with_name(out_path.name + ".part")
    lines = 1
    with part.open("wb") as out:
        out.write(header)
        for path in inputs:
            with Path(path).open("rb") as fh:
                fh.readline()
                while chunk := fh.read(_CHUNK):
                    lines += chunk.count(b"\n")
                    out.write(chunk)
    if expected is None:
        part.replace(out_path)
    else:
        _finalise(part, out_path, expected)
    return lines


# --- pipeline ---------------------------------------------------------------


def prepare_iris(
    data_dir: Path,
    *,
    manifest: IrisManifest | None = None,
    archive: Path | None = None,
    opener: Opener | None = None,
) -> IrisPaths:
    """Download, extract and merge the IRIS event set for one basin.

    Idempotent: every file that is already present and verified is kept.

    Parameters
    ----------
    data_dir : Path
        Root of the IRIS data (see the module docstring for the layout).
    manifest : IrisManifest, optional
        Defaults to the manifest shipped with this package.
    archive : Path, optional
        An existing copy of the IRIS zip to use instead of downloading it. It
        is verified against the manifest and read in place, not copied.
    opener : callable, optional
        Opens a URL for reading bytes (for tests). Defaults to urllib.

    Returns
    -------
    IrisPaths
        The verified files and what was done to each.

    Raises
    ------
    ChecksumMismatchError
        If any downloaded, extracted, existing or merged file does not match
        the manifest.
    IrisDataError, MergeFormatError
        See :func:`download_file`, :func:`extract_members` and
        :func:`merge_track_files`.
    """
    manifest = manifest or load_manifest()
    raw_dir = data_dir / "raw"
    actions: dict[str, str] = {}

    def record(name: str, created: bool) -> None:
        actions[name] = "created" if created else "verified"

    if archive is not None:
        verify_file(archive, manifest.archive)
        archive_path = archive
        record(manifest.archive.name, False)
    else:
        archive_path, created = download_file(manifest.archive, raw_dir, opener=opener)
        record(manifest.archive.name, created)
    readme_path, created = download_file(manifest.readme, raw_dir, opener=opener)
    record(manifest.readme.name, created)

    member_paths, created_list = extract_members(
        archive_path, manifest.members, raw_dir / "IRIS_event_set"
    )
    for member, created in zip(manifest.members, created_list, strict=True):
        record(member.name, created)

    merged_path = data_dir / "transformed" / manifest.merged.name
    if _already_verified(merged_path, manifest.merged):
        record(manifest.merged.name, False)
    else:
        merge_track_files(member_paths, merged_path, expected=manifest.merged)
        record(manifest.merged.name, True)

    return IrisPaths(
        archive=archive_path,
        readme=readme_path,
        members=tuple(member_paths),
        merged=merged_path,
        actions=actions,
    )


def main(argv: Sequence[str] | None = None) -> int:
    """Command-line entry point; see ``--help``.

    Parameters
    ----------
    argv : sequence of str, optional
        Arguments; defaults to ``sys.argv[1:]``.

    Returns
    -------
    int
        Exit status: 0 on success, 1 on an IRIS data error.
    """
    parser = argparse.ArgumentParser(
        prog="python -m parametric_insurance_design_climada.iris",
        description=(
            "Download the IRIS event set from figshare, extract the ten North "
            "Atlantic 1,000-year files and merge them into one 10,000-year "
            "catalogue, verifying every file against the pinned SHA256 "
            "manifest. Re-running skips files that are already verified."
        ),
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        required=True,
        help="IRIS data root (git-ignored), e.g. ../../data/iris",
    )
    parser.add_argument(
        "--archive",
        type=Path,
        default=None,
        help="use this local IRIS_event_set.zip instead of downloading it",
    )
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    manifest = load_manifest()
    try:
        paths = prepare_iris(args.data_dir, manifest=manifest, archive=args.archive)
    except IrisDataError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    for name, action in paths.actions.items():
        print(f"{action:9s} {name}")
    print(f"merged catalogue: {paths.merged}")
    print(f"sha256: {manifest.merged.sha256}")
    print(f"licence: {manifest.licence}; cite: {manifest.citation}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
