"""GUI-independent part: talk to GitHub and import a package into a collection."""
from __future__ import annotations

import json
import os
import ssl
import tempfile
import urllib.error
import urllib.request
from dataclasses import dataclass

from anki.collection import (
    Collection,
    ImportAnkiPackageOptions,
    ImportAnkiPackageRequest,
    ImportLogWithChanges,
)
from anki.import_export_pb2 import ImportAnkiPackageUpdateCondition

API = "https://api.github.com"
LAST_TAG_KEY = "ijcHskLastImportedTag"  # stored in the collection, so it syncs


class UpdateError(Exception):
    pass


@dataclass
class Release:
    tag: str
    name: str
    url: str          # release page
    asset_url: str    # API url of the asset (works for private repos too)
    notes: str


def _ssl_context() -> ssl.SSLContext:
    try:
        import certifi  # bundled with Anki
        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


def _request(url: str, token: str, accept: str) -> urllib.request.Request:
    req = urllib.request.Request(url, headers={
        "Accept": accept,
        "User-Agent": "ijc-hsk-anki-addon",
        "X-GitHub-Api-Version": "2022-11-28",
    })
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    return req


def _open(req: urllib.request.Request, timeout: int = 30):
    try:
        return urllib.request.urlopen(req, timeout=timeout, context=_ssl_context())
    except urllib.error.HTTPError as e:
        if e.code == 404:
            raise UpdateError(
                "No release found (or the repository is private and "
                "github_token is missing/invalid)."
            ) from e
        if e.code in (401, 403):
            raise UpdateError(f"GitHub refused access (HTTP {e.code}). Check github_token.") from e
        raise UpdateError(f"GitHub returned HTTP {e.code}.") from e
    except urllib.error.URLError as e:
        raise UpdateError(f"Can't reach GitHub: {e.reason}") from e


def parse_release(data: dict, asset_name: str) -> Release:
    for asset in data.get("assets", []):
        if asset.get("name") == asset_name:
            return Release(
                tag=data["tag_name"],
                name=data.get("name") or data["tag_name"],
                url=data.get("html_url", ""),
                asset_url=asset["url"],
                notes=data.get("body") or "",
            )
    raise UpdateError(f"Release {data.get('tag_name')} has no file named {asset_name}.")


def latest_release(repo: str, asset_name: str, token: str = "") -> Release:
    req = _request(f"{API}/repos/{repo}/releases/latest", token, "application/vnd.github+json")
    with _open(req) as resp:
        return parse_release(json.load(resp), asset_name)


def download(release: Release, token: str = "") -> str:
    """Download the asset to a temp file and return its path."""
    req = _request(release.asset_url, token, "application/octet-stream")
    fd, path = tempfile.mkstemp(prefix="ijc-hsk-", suffix=".apkg")
    try:
        with _open(req, timeout=120) as resp, os.fdopen(fd, "wb") as out:
            while chunk := resp.read(1 << 16):
                out.write(chunk)
    except Exception:
        os.unlink(path)
        raise
    return path


def import_package(col: Collection, path: str) -> ImportLogWithChanges:
    """Import with the repo as the source of truth.

    Notes and the note type are always overwritten with the package contents
    (matched by GUID), but scheduling and deck options are never touched, so
    review history stays exactly as it is.
    """
    always = ImportAnkiPackageUpdateCondition.IMPORT_ANKI_PACKAGE_UPDATE_CONDITION_ALWAYS
    return col.import_anki_package(ImportAnkiPackageRequest(
        package_path=path,
        options=ImportAnkiPackageOptions(
            merge_notetypes=True,
            update_notes=always,
            update_notetypes=always,
            with_scheduling=False,
            with_deck_configs=False,
        ),
    ))


def last_imported_tag(col: Collection) -> str:
    return col.get_config(LAST_TAG_KEY, "")


def set_last_imported_tag(col: Collection, tag: str) -> None:
    col.set_config(LAST_TAG_KEY, tag)


def summary(result: ImportLogWithChanges) -> str:
    log = result.log
    parts = []
    if log.new:
        parts.append(f"{len(log.new)} new")
    if log.updated:
        parts.append(f"{len(log.updated)} updated")
    problems = len(log.conflicting) + len(log.missing_notetype) + len(log.missing_deck)
    if problems:
        parts.append(f"{problems} skipped")
    return ", ".join(parts) or "no note changes"
