import os
import stat
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest

import src.obsidian_integration.manager as manager_module
from src.obsidian_integration.manager import ObsidianManager


@pytest.fixture
def manager(tmp_path):
    vault = tmp_path / "vault"
    vault.mkdir()
    return ObsidianManager(vault_path=str(vault))


def test_concurrent_writes_use_distinct_temporary_files(manager, monkeypatch):
    replacement_sources = []
    replace_barrier = Barrier(2)
    real_replace = manager_module.os.replace

    def record_replace(source, target, **kwargs):
        replacement_sources.append(os.fspath(source))
        replace_barrier.wait(timeout=5)
        return real_replace(source, target, **kwargs)

    monkeypatch.setattr(manager_module.os, "replace", record_replace)

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [
            executor.submit(manager.write_note, "projection.md", f"content-{i}")
            for i in range(2)
        ]
        for future in futures:
            future.result()

    assert len(replacement_sources) == 2
    assert len(set(replacement_sources)) == 2


def test_failed_replace_preserves_existing_note(manager, monkeypatch):
    manager.write_note("projection.md", "canonical content")

    def fail_replace(source, target, **_kwargs):
        raise OSError("simulated replacement failure")

    monkeypatch.setattr(manager_module.os, "replace", fail_replace)

    with pytest.raises(OSError, match="simulated replacement failure"):
        manager.write_note("projection.md", "new content")

    assert manager.read_note("projection.md") == "canonical content"
    assert [
        path for path in manager.vault_path.iterdir() if path.name != "projection.md"
    ] == []


def test_retry_overwrites_with_identical_bytes(manager):
    content = "# Projection\n\ncanonical bytes\n"

    manager.write_note("projection.md", content)
    first_bytes = (manager.vault_path / "projection.md").read_bytes()
    manager.write_note("projection.md", content)
    second_bytes = (manager.vault_path / "projection.md").read_bytes()

    assert first_bytes == content.encode("utf-8")
    assert second_bytes == first_bytes


def test_overwrite_preserves_existing_note_mode(manager):
    note_path = manager.vault_path / "projection.md"
    note_path.write_text("old content", encoding="utf-8")
    note_path.chmod(0o640)

    manager.write_note("projection.md", "new content")

    assert stat.S_IMODE(note_path.stat().st_mode) == 0o640


def test_new_note_uses_normal_creation_mode(manager):
    note_path = manager.vault_path / "projection.md"
    original_umask = os.umask(0o027)
    try:
        manager.write_note("projection.md", "new content")
    finally:
        os.umask(original_umask)

    assert stat.S_IMODE(note_path.stat().st_mode) == 0o640


def test_non_text_content_error_is_not_reclassified(manager):
    with pytest.raises(TypeError):
        manager.write_note("projection.md", b"not text")

    assert list(manager.vault_path.iterdir()) == []


def test_new_note_creation_does_not_invoke_umask(manager, monkeypatch):
    probe_path = manager.vault_path / "mode-probe"
    probe_path.write_text("probe", encoding="utf-8")
    expected_mode = stat.S_IMODE(probe_path.stat().st_mode)
    probe_path.unlink()

    def fail_umask(*args):
        raise AssertionError("write_note must not change process umask")

    monkeypatch.setattr(manager_module.os, "umask", fail_umask)
    manager.write_note("projection.md", "new content")

    assert stat.S_IMODE((manager.vault_path / "projection.md").stat().st_mode) == (
        expected_mode
    )


def test_overwrite_rejects_existing_target_symlink(manager, tmp_path):
    outside = tmp_path / "outside.md"
    outside.write_text("outside content", encoding="utf-8")
    (manager.vault_path / "projection.md").symlink_to(outside)

    with pytest.raises(ValueError, match="symbolic link"):
        manager.write_note("projection.md", "new content")

    assert outside.read_text(encoding="utf-8") == "outside content"
    assert (manager.vault_path / "projection.md").is_symlink()


def test_overwrite_flushes_file_and_parent_directory(manager, monkeypatch):
    fsync_modes = []

    def record_fsync(file_descriptor):
        fsync_modes.append(os.fstat(file_descriptor).st_mode)

    monkeypatch.setattr(manager_module.os, "fsync", record_fsync)

    manager.write_note("projection.md", "durable content")

    assert sum(stat.S_ISREG(mode) for mode in fsync_modes) == 1
    assert sum(stat.S_ISDIR(mode) for mode in fsync_modes) == 1


def test_parent_directory_sync_failure_reports_replacement_applied(
    manager, monkeypatch
):
    real_fsync = manager_module.os.fsync

    def fail_directory_fsync(file_descriptor):
        if stat.S_ISDIR(os.fstat(file_descriptor).st_mode):
            raise OSError("simulated directory sync failure")
        return real_fsync(file_descriptor)

    monkeypatch.setattr(manager_module.os, "fsync", fail_directory_fsync)

    with pytest.raises(Exception) as error_info:
        manager.write_note("projection.md", "new content")

    error = error_info.value
    assert manager.read_note("projection.md") == "new content"
    projection_error_type = getattr(manager_module, "ObsidianProjectionError", None)
    assert projection_error_type is not None
    assert isinstance(error, projection_error_type)
    assert error.replacement_applied is True
    assert error.stage == "parent_directory_sync"
    assert error.reason == "directory_sync_failed"


@pytest.mark.skipif(os.name != "posix", reason="descriptor-relative POSIX behavior")
def test_parent_path_swap_cannot_redirect_replacement_outside_vault(
    manager, monkeypatch, tmp_path
):
    outside = tmp_path / "outside"
    outside.mkdir()
    original_parent = manager.vault_path / "Memory" / "reviewed"
    original_parent.mkdir(parents=True)
    held_parent = manager.vault_path / "held-parent"
    real_replace = manager_module.os.replace

    def swap_parent_then_replace(source, target, *, src_dir_fd, dst_dir_fd):
        original_parent.rename(held_parent)
        original_parent.symlink_to(outside, target_is_directory=True)
        return real_replace(
            source,
            target,
            src_dir_fd=src_dir_fd,
            dst_dir_fd=dst_dir_fd,
        )

    monkeypatch.setattr(manager_module.os, "replace", swap_parent_then_replace)

    manager.write_note("Memory/reviewed/brief.md", "confined")

    assert (held_parent / "brief.md").read_text(encoding="utf-8") == "confined"
    assert not (outside / "brief.md").exists()


def test_overwrite_writes_exact_utf8_bytes_without_newline_translation(manager):
    content = "first line\r\nsecond line\nemoji: \N{CITYSCAPE AT DUSK}\rthird"

    manager.write_note("projection.md", content)

    assert (manager.vault_path / "projection.md").read_bytes() == content.encode(
        "utf-8"
    )


def test_directory_sync_failure_never_unlinks_reappearing_temp_entry(
    manager, monkeypatch
):
    real_fsync = manager_module.os.fsync
    real_replace = manager_module.os.replace
    replacement_source: list[str] = []
    unlink_calls: list[tuple[str, int | None]] = []

    def record_replace(source, target, *, src_dir_fd, dst_dir_fd):
        replacement_source.append(os.fspath(source))
        return real_replace(
            source,
            target,
            src_dir_fd=src_dir_fd,
            dst_dir_fd=dst_dir_fd,
        )

    def fail_directory_fsync(file_descriptor):
        if stat.S_ISDIR(os.fstat(file_descriptor).st_mode):
            assert replacement_source
            reappeared_fd = os.open(
                replacement_source[0],
                os.O_CREAT | os.O_EXCL | os.O_WRONLY,
                0o600,
                dir_fd=file_descriptor,
            )
            try:
                os.write(reappeared_fd, b"reappeared")
            finally:
                os.close(reappeared_fd)
            raise OSError("simulated directory sync failure")
        return real_fsync(file_descriptor)

    def record_unlink(path, *, dir_fd=None):
        unlink_calls.append((os.fspath(path), dir_fd))

    monkeypatch.setattr(manager_module.os, "replace", record_replace)
    monkeypatch.setattr(manager_module.os, "fsync", fail_directory_fsync)
    monkeypatch.setattr(manager_module.os, "unlink", record_unlink)

    with pytest.raises(Exception) as error_info:
        manager.write_note("projection.md", "new content")

    assert error_info.value.replacement_applied is True
    assert unlink_calls == []
    assert (manager.vault_path / replacement_source[0]).read_text(
        encoding="utf-8"
    ) == "reappeared"


def test_windows_rejection_precedes_all_write_side_effects(manager, monkeypatch):
    side_effects: list[str] = []

    monkeypatch.setattr(manager_module.os, "name", "nt")
    monkeypatch.setattr(
        manager_module.os,
        "open",
        lambda *_args, **_kwargs: side_effects.append("open"),
    )
    monkeypatch.setattr(
        manager_module.os,
        "mkdir",
        lambda *_args, **_kwargs: side_effects.append("mkdir"),
    )
    monkeypatch.setattr(
        manager_module.os,
        "replace",
        lambda *_args, **_kwargs: side_effects.append("replace"),
    )

    with pytest.raises(NotImplementedError, match="POSIX"):
        manager.write_note("new/folder/projection.md", "new content")

    assert side_effects == []
    assert list(manager.vault_path.iterdir()) == []


def test_relative_vault_root_remains_anchored_after_cwd_change(tmp_path, monkeypatch):
    initialized_cwd = tmp_path / "initialized"
    later_cwd = tmp_path / "later"
    initialized_vault = initialized_cwd / "vault"
    redirected_vault = later_cwd / "vault"
    initialized_vault.mkdir(parents=True)
    redirected_vault.mkdir(parents=True)
    monkeypatch.chdir(initialized_cwd)
    manager = ObsidianManager(vault_path="vault")

    monkeypatch.chdir(later_cwd)
    manager.write_note("projection.md", "anchored content")

    assert (initialized_vault / "projection.md").read_text(encoding="utf-8") == (
        "anchored content"
    )
    assert not (redirected_vault / "projection.md").exists()


def test_replaced_absolute_vault_ancestor_cannot_redirect_write(tmp_path):
    configured_parent = tmp_path / "configured"
    initialized_vault = configured_parent / "vault"
    initialized_vault.mkdir(parents=True)
    manager = ObsidianManager(vault_path=str(initialized_vault))

    relocated_parent = tmp_path / "relocated"
    configured_parent.rename(relocated_parent)
    redirected_vault = configured_parent / "vault"
    redirected_vault.mkdir(parents=True)

    with pytest.raises(ValueError, match="identity"):
        manager.write_note("projection.md", "must remain confined")

    assert not (redirected_vault / "projection.md").exists()
    assert not (relocated_parent / "vault" / "projection.md").exists()


def test_created_parent_entries_are_synced_before_temp_and_replacement(
    manager, monkeypatch
):
    events: list[tuple[str, str | int]] = []
    real_fsync = manager_module.os.fsync
    real_mkdir = manager_module.os.mkdir
    real_open = manager_module.os.open
    real_replace = manager_module.os.replace
    vault_inode = manager.vault_path.stat().st_ino

    def record_mkdir(path, mode=0o777, *, dir_fd=None):
        assert dir_fd is not None
        events.append(("mkdir", os.fspath(path)))
        return real_mkdir(path, mode, dir_fd=dir_fd)

    def record_fsync(file_descriptor):
        if stat.S_ISDIR(os.fstat(file_descriptor).st_mode):
            events.append(("dir_fsync", os.fstat(file_descriptor).st_ino))
        return real_fsync(file_descriptor)

    def record_open(path, flags, mode=0o777, *, dir_fd=None):
        if flags & os.O_CREAT:
            assert dir_fd is not None
            events.append(("temp_open", os.fstat(dir_fd).st_ino))
        return real_open(path, flags, mode, dir_fd=dir_fd)

    def record_replace(source, target, *, src_dir_fd, dst_dir_fd):
        assert src_dir_fd == dst_dir_fd
        events.append(("replace", os.fstat(dst_dir_fd).st_ino))
        return real_replace(
            source,
            target,
            src_dir_fd=src_dir_fd,
            dst_dir_fd=dst_dir_fd,
        )

    monkeypatch.setattr(manager_module.os, "mkdir", record_mkdir)
    monkeypatch.setattr(manager_module.os, "fsync", record_fsync)
    monkeypatch.setattr(manager_module.os, "open", record_open)
    monkeypatch.setattr(manager_module.os, "replace", record_replace)

    manager.write_note("outer/inner/projection.md", "durable parents")

    outer_inode = (manager.vault_path / "outer").stat().st_ino
    inner_inode = (manager.vault_path / "outer" / "inner").stat().st_ino
    assert events == [
        ("mkdir", "outer"),
        ("dir_fsync", vault_inode),
        ("mkdir", "inner"),
        ("dir_fsync", outer_inode),
        ("temp_open", inner_inode),
        ("replace", inner_inode),
        ("dir_fsync", inner_inode),
    ]


@pytest.mark.parametrize("failed_directory_sync", [1, 2])
def test_created_parent_sync_failure_precedes_temp_and_replacement(
    manager, monkeypatch, failed_directory_sync
):
    real_fsync = manager_module.os.fsync
    real_open = manager_module.os.open
    directory_syncs = 0
    temp_opened = False
    replacement_attempted = False

    def fail_selected_directory_fsync(file_descriptor):
        nonlocal directory_syncs
        if stat.S_ISDIR(os.fstat(file_descriptor).st_mode):
            directory_syncs += 1
            if directory_syncs == failed_directory_sync:
                raise OSError("simulated created-parent sync failure")
        return real_fsync(file_descriptor)

    def record_open(path, flags, mode=0o777, *, dir_fd=None):
        nonlocal temp_opened
        if flags & os.O_CREAT:
            temp_opened = True
        return real_open(path, flags, mode, dir_fd=dir_fd)

    def record_replace(*_args, **_kwargs):
        nonlocal replacement_attempted
        replacement_attempted = True

    monkeypatch.setattr(manager_module.os, "fsync", fail_selected_directory_fsync)
    monkeypatch.setattr(manager_module.os, "open", record_open)
    monkeypatch.setattr(manager_module.os, "replace", record_replace)

    with pytest.raises(manager_module.ObsidianProjectionError) as error_info:
        manager.write_note("outer/inner/projection.md", "not yet projectable")

    assert error_info.value.stage == "parent_directory"
    assert error_info.value.replacement_applied is False
    assert temp_opened is False
    assert replacement_attempted is False


def test_windows_append_retains_legacy_behavior(manager, monkeypatch):
    note_path = manager.vault_path / "projection.md"
    note_path.write_text("existing", encoding="utf-8")
    monkeypatch.setattr(manager_module.os, "name", "nt")

    manager.write_note("projection.md", " + appended", overwrite=False)

    assert note_path.read_text(encoding="utf-8") == "existing + appended"


@pytest.mark.skipif(os.name != "posix", reason="POSIX NAME_MAX behavior")
def test_maximum_length_target_name_uses_bounded_temporary_name(manager):
    name_max = os.pathconf(manager.vault_path, "PC_NAME_MAX")
    suffix = ".md"
    target_name = f"{'n' * (name_max - len(suffix))}{suffix}"

    manager.write_note(target_name, "maximum-length target")

    assert (manager.vault_path / target_name).read_text(encoding="utf-8") == (
        "maximum-length target"
    )
