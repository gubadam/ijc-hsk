"""IJC HSK: import new deck releases from GitHub and sync them to AnkiWeb.

On startup (after Anki's own startup sync) the add-on checks the latest GitHub
release of the deck repository. If its tag differs from the last imported one,
the package is downloaded, imported (notes matched by GUID, review history
untouched) and Anki syncs with AnkiWeb, so other devices get the new cards.
"""
from __future__ import annotations

import os

from aqt import gui_hooks, mw
from aqt.operations import CollectionOp, QueryOp
from aqt.qt import QAction, QFileDialog
from aqt.utils import openLink, showWarning, tooltip

from . import updater

TITLE = "IJC HSK"
_state = {"startup_pending": False, "busy": False}


def _config() -> dict:
    return mw.addonManager.getConfig(__name__) or {}


# ------------------------------------------------------------------ flow ---

def check_for_updates(manual: bool = False) -> None:
    if _state["busy"] or not mw.col:
        return
    cfg = _config()
    repo, asset, token = cfg.get("repo", ""), cfg.get("asset", ""), cfg.get("github_token", "")
    if not repo or not asset:
        showWarning(f"{TITLE}: set 'repo' and 'asset' in the add-on config.")
        return
    _state["busy"] = True
    last = updater.last_imported_tag(mw.col)
    placed = updater.placed_tag(mw.col) if cfg.get("place_cards", True) else last

    def fetch(_col):
        release = updater.latest_release(repo, asset, token)
        if release.tag == last and release.tag == placed:
            return release, None
        return release, updater.download(release, token)

    def on_fetched(result) -> None:
        release, path = result
        if path is None:
            _state["busy"] = False
            if manual:
                tooltip(f"{TITLE}: decks are up to date ({release.tag}).")
            return
        _import(release, path, cfg)

    def on_error(err: Exception) -> None:
        _state["busy"] = False
        if manual or not isinstance(err, updater.UpdateError):
            showWarning(f"{TITLE}: update check failed.\n\n{err}")
        # automatic check: stay quiet about network problems (e.g. offline)

    # network only, so don't hold the collection lock while downloading
    op = QueryOp(parent=mw, op=fetch, success=on_fetched).failure(on_error).without_collection()
    if manual:
        op = op.with_progress(f"{TITLE}: checking GitHub…")
    op.run_in_background()


def _import(release: updater.Release, path: str, cfg: dict) -> None:
    def op(col):
        result = updater.import_package(col, path)
        moved = 0
        if cfg.get("place_cards", True):
            moved = updater.place_cards(col, updater.package_layout(path))
            updater.set_placed_tag(col, release.tag)
        updater.set_last_imported_tag(col, release.tag)
        return result, moved

    def done(out) -> None:
        result, moved = out
        _cleanup(path)
        _state["busy"] = False
        tooltip(f"{TITLE}: imported {release.tag} — {updater.summary(result, moved)}.", period=6000)
        if cfg.get("sync_after_import", True) and mw.pm.sync_auth():
            mw.on_sync_button_clicked()

    def failed(err: Exception) -> None:
        _cleanup(path)
        _state["busy"] = False
        showWarning(f"{TITLE}: importing {release.tag} failed.\n\n{err}")

    CollectionOp(parent=mw, op=op).success(done).failure(failed).run_in_background()


def import_local_file() -> None:
    """Import a locally built .apkg the same way as a release (incl. moving cards)."""
    if _state["busy"] or not mw.col:
        return
    path, _ = QFileDialog.getOpenFileName(mw, f"{TITLE}: import deck package", "", "Anki package (*.apkg)")
    if not path:
        return
    cfg = _config()
    _state["busy"] = True

    def op(col):
        result = updater.import_package(col, path)
        moved = updater.place_cards(col, updater.package_layout(path)) if cfg.get("place_cards", True) else 0
        return result, moved

    def done(out) -> None:
        result, moved = out
        _state["busy"] = False
        tooltip(f"{TITLE}: imported {os.path.basename(path)} — {updater.summary(result, moved)}.", period=6000)
        if cfg.get("sync_after_import", True) and mw.pm.sync_auth():
            mw.on_sync_button_clicked()

    def failed(err: Exception) -> None:
        _state["busy"] = False
        showWarning(f"{TITLE}: importing {os.path.basename(path)} failed.\n\n{err}")

    CollectionOp(parent=mw, op=op).success(done).failure(failed).run_in_background()


def _cleanup(path: str) -> None:
    try:
        os.unlink(path)
    except OSError:
        pass


def _open_releases() -> None:
    repo = _config().get("repo", "")
    if repo:
        openLink(f"https://github.com/{repo}/releases")


# ----------------------------------------------------------------- hooks ---

def _on_profile_open() -> None:
    if not _config().get("check_on_startup", True):
        return
    if mw.can_auto_sync():
        # Anki syncs right after this hook; check once that sync has finished,
        # so we import on top of the latest collection from AnkiWeb.
        _state["startup_pending"] = True
    else:
        mw.progress.single_shot(1500, check_for_updates)


def _on_sync_finished() -> None:
    if _state["startup_pending"]:
        _state["startup_pending"] = False
        mw.progress.single_shot(500, check_for_updates)


def _setup_menu() -> None:
    menu = mw.form.menuTools
    menu.addSeparator()
    check = QAction(f"{TITLE}: check for updates", mw)
    check.triggered.connect(lambda: check_for_updates(manual=True))
    menu.addAction(check)
    local = QAction(f"{TITLE}: import local .apkg…", mw)
    local.triggered.connect(import_local_file)
    menu.addAction(local)
    releases = QAction(f"{TITLE}: open releases (changelog)", mw)
    releases.triggered.connect(_open_releases)
    menu.addAction(releases)


gui_hooks.profile_did_open.append(_on_profile_open)
gui_hooks.sync_did_finish.append(_on_sync_finished)
_setup_menu()
