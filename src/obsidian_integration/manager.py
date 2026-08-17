"""Contain vault file operations behind validated Obsidian-relative paths."""

import errno
import ntpath
import os
import secrets
import stat
from pathlib import Path, PurePosixPath

from ..utils.helpers import logger, sanitize_for_log

_TEMP_FILE_ATTEMPTS = 10


def _validated_relative_parts(relative_path: str) -> tuple[str, ...]:
    """Return canonical POSIX components for one vault-relative path."""
    if not isinstance(relative_path, str) or not relative_path:
        raise ValueError("vault path must not be empty")
    raw_parts = relative_path.split("/")
    drive, _ = ntpath.splitdrive(relative_path)
    if (
        drive
        or "\\" in relative_path
        or "\x00" in relative_path
        or any(part in {"", ".", ".."} or not part.strip() for part in raw_parts)
    ):
        raise ValueError("vault path must use one canonical POSIX form")
    requested = PurePosixPath(relative_path)
    if requested.is_absolute():
        raise ValueError("vault path must be relative and remain within the vault root")
    return requested.parts


def _directory_open_flags() -> int:
    """Build flags that reject symlinks while opening a directory."""
    return os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW


def _open_unique_temp_file(parent_fd: int) -> tuple[int, str]:
    """Create a cryptographically named staging file below an open directory."""
    flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW
    name_max = os.fpathconf(parent_fd, "PC_NAME_MAX")
    if name_max == -1:
        name_max = 33
    if name_max < 2:
        raise OSError(errno.ENAMETOOLONG, "directory cannot hold a temporary name")
    token_characters = min(32, name_max - 1)
    for _ in range(_TEMP_FILE_ATTEMPTS):
        candidate = f".{secrets.token_hex(16)[:token_characters]}"
        try:
            file_descriptor = os.open(candidate, flags, 0o644, dir_fd=parent_fd)
        except FileExistsError:
            continue
        return file_descriptor, candidate
    raise OSError(errno.EEXIST, "unable to create unique projection temporary file")


class ObsidianProjectionError(OSError):
    """Report a projection failure and whether replacement already succeeded."""

    def __init__(
        self,
        message: str,
        *,
        stage: str,
        reason: str,
        replacement_applied: bool,
    ) -> None:
        super().__init__(message)
        self.stage = stage
        self.reason = reason
        self.replacement_applied = replacement_applied


class ObsidianManager:
    """Provide the ObsidianManager abstraction used by this module."""

    def __init__(self, vault_path: str | None = None):
        # Re-read OBSIDIAN_VAULT_PATH at call time so tests that
        # monkeypatch src.mcp.config.OBSIDIAN_VAULT_PATH take effect.
        # A def-time default would freeze the original module-load value.
        if vault_path is None:
            from src.mcp.config import OBSIDIAN_VAULT_PATH as _vault

            vault_path = _vault
        configured_path = Path(vault_path)
        try:
            resolved_path = configured_path.resolve(strict=True)
        except (FileNotFoundError, NotADirectoryError) as exc:
            logger.error("Obsidian vault path does not exist")
            raise FileNotFoundError(
                f"Obsidian vault path not found: {configured_path}"
            ) from exc
        if not resolved_path.is_dir():
            logger.error("Obsidian vault path does not exist")
            raise FileNotFoundError(f"Obsidian vault path not found: {configured_path}")
        self.vault_path = resolved_path
        root_stat = self.vault_path.stat()
        self._vault_identity = (root_stat.st_dev, root_stat.st_ino)
        logger.info("Obsidian Manager initialized")

    def _get_full_path(self, relative_path: str) -> Path:
        """Resolve a vault-relative path and reject vault escapes."""
        requested = PurePosixPath(*_validated_relative_parts(relative_path))

        vault_root = self.vault_path.resolve()
        full_path = vault_root.joinpath(*requested.parts).resolve()
        try:
            resolved_relative = full_path.relative_to(vault_root)
        except ValueError as exc:
            raise ValueError("vault path escapes configured vault root") from exc
        if resolved_relative.as_posix() != requested.as_posix():
            raise ValueError("vault path must resolve to its canonical lexical path")
        return full_path

    def _open_vault_root(self) -> int:
        """Open the initialized vault identity without accepting path replacement."""
        root_fd = os.open(self.vault_path, _directory_open_flags())
        try:
            root_stat = os.fstat(root_fd)
            if (root_stat.st_dev, root_stat.st_ino) != self._vault_identity:
                raise ValueError("configured vault root identity changed")
            return root_fd
        except BaseException:
            os.close(root_fd)
            raise

    def _open_parent_directory(self, parent_parts: tuple[str, ...]) -> int:
        """Traverse or create parents without following path components."""
        current_fd = self._open_vault_root()
        try:
            for component in parent_parts:
                try:
                    next_fd = os.open(
                        component, _directory_open_flags(), dir_fd=current_fd
                    )
                except FileNotFoundError:
                    try:
                        os.mkdir(component, 0o755, dir_fd=current_fd)
                    except FileExistsError:
                        pass
                    os.fsync(current_fd)
                    next_fd = os.open(
                        component, _directory_open_flags(), dir_fd=current_fd
                    )
                except OSError as exc:
                    component_stat = os.stat(
                        component, dir_fd=current_fd, follow_symlinks=False
                    )
                    if stat.S_ISLNK(component_stat.st_mode):
                        raise ValueError(
                            "vault path must resolve to its canonical lexical path"
                        ) from exc
                    raise
                else:
                    try:
                        os.fsync(current_fd)
                    except BaseException:
                        os.close(next_fd)
                        raise
                os.close(current_fd)
                current_fd = next_fd
            return current_fd
        except BaseException:
            os.close(current_fd)
            raise

    @staticmethod
    def _existing_target_mode(parent_fd: int, target_name: str) -> int | None:
        """Return a regular target's mode while rejecting a target symlink."""
        try:
            target_stat = os.stat(target_name, dir_fd=parent_fd, follow_symlinks=False)
        except FileNotFoundError:
            return None
        if stat.S_ISLNK(target_stat.st_mode):
            raise ValueError("vault target must not be a symbolic link")
        return stat.S_IMODE(target_stat.st_mode)

    def _get_folder_path(self, relative_folder_path: str) -> Path:
        """Resolve a folder path while allowing the vault root as an empty sentinel."""
        if relative_folder_path == "":
            return self.vault_path.resolve()
        return self._get_full_path(relative_folder_path)

    def read_note(self, relative_path: str) -> str | None:
        """Reads the content of an Obsidian note.

        Args:
            relative_path (str): Vault-relative path associated with the note or record.

        Returns:
            str | None: Resulting str | None value produced by the operation.
        """
        full_path = self._get_full_path(relative_path)
        if not full_path.is_file():
            logger.warning("Note not found: %s", sanitize_for_log(relative_path))
            return None
        with open(full_path, "r", encoding="utf-8") as f:
            content = f.read()
            logger.debug("Read note: %s", sanitize_for_log(relative_path))
            return content

    def write_note(self, relative_path: str, content: str, overwrite: bool = True):
        """Writes content to an Obsidian note. Creates directories if necessary.

        Overwrite mode writes to a temp file and ``os.replace``s it onto the
        target so a mid-write failure (e.g. disk full) can't leave a
        truncated file behind. Append mode is unchanged.

        Args:
            relative_path (str): Vault-relative path associated with the note or record.
            content (str): Primary content payload to parse, store, or process.
            overwrite (bool): Overwrite value used by this operation.

        Returns:
            None: This function does not return a value.
        """
        if overwrite:
            if os.name != "posix":
                raise NotImplementedError(
                    "durable Obsidian projection is currently POSIX-only"
                )
            if not isinstance(content, str):
                raise TypeError("note content must be text")
            encoded_content = content.encode("utf-8")
            path_parts = _validated_relative_parts(relative_path)
            target_name = path_parts[-1]
            parent_fd: int | None = None
            temp_name: str | None = None
            temp_fd: int | None = None
            stage = "parent_directory"
            replacement_applied = False
            try:
                parent_fd = self._open_parent_directory(path_parts[:-1])
                target_mode = self._existing_target_mode(parent_fd, target_name)
                stage = "temporary_write"
                temp_fd, temp_name = _open_unique_temp_file(parent_fd)
                if target_mode is not None:
                    os.fchmod(temp_fd, target_mode)
                stream = os.fdopen(temp_fd, "wb")
                temp_fd = None
                with stream as f:
                    f.write(encoded_content)
                    f.flush()
                    os.fsync(f.fileno())
                stage = "replacement"
                os.replace(
                    temp_name,
                    target_name,
                    src_dir_fd=parent_fd,
                    dst_dir_fd=parent_fd,
                )
                replacement_applied = True

                stage = "parent_directory_sync"
                os.fsync(parent_fd)
            except Exception as exc:
                if temp_fd is not None:
                    try:
                        os.close(temp_fd)
                    except OSError:
                        pass
                if (
                    temp_name is not None
                    and parent_fd is not None
                    and not replacement_applied
                ):
                    try:
                        os.unlink(temp_name, dir_fd=parent_fd)
                    except FileNotFoundError:
                        pass
                if not isinstance(exc, OSError):
                    raise
                reason = {
                    "parent_directory": "parent_directory_failed",
                    "temporary_write": "temporary_write_failed",
                    "replacement": "replacement_failed",
                    "parent_directory_sync": "directory_sync_failed",
                }.get(stage, "projection_failed")
                raise ObsidianProjectionError(
                    f"Obsidian projection failed during {stage}: {exc}",
                    stage=stage,
                    reason=reason,
                    replacement_applied=replacement_applied,
                ) from exc
            finally:
                if parent_fd is not None:
                    os.close(parent_fd)
            logger.info(
                "Wrote note: %s (mode: w, atomic)", sanitize_for_log(relative_path)
            )
        else:
            full_path = self._get_full_path(relative_path)
            full_path.parent.mkdir(parents=True, exist_ok=True)
            with open(full_path, "a", encoding="utf-8") as f:
                f.write(content)
            logger.info("Wrote note: %s (mode: a)", sanitize_for_log(relative_path))

    def list_notes_in_folder(
        self, relative_folder_path: str, suffix: str = ".md"
    ) -> list[str]:
        """Lists all notes (Markdown files) in a specified folder.

        Args:
            relative_folder_path (str): Vault-relative folder path to inspect or create.
            suffix (str): Filename suffix used for filtering.

        Returns:
            list[str]: List containing the resulting items.
        """
        full_path = self._get_folder_path(relative_folder_path)
        if not full_path.is_dir():
            logger.warning(
                "Folder not found: %s", sanitize_for_log(relative_folder_path)
            )
            return []
        notes = [
            str(f.relative_to(full_path))
            for f in full_path.iterdir()
            if f.is_file() and f.suffix == suffix
        ]
        logger.debug(
            "Listed %s notes in %s", len(notes), sanitize_for_log(relative_folder_path)
        )
        return notes

    def create_folder(self, relative_folder_path: str):
        """Ensures a folder exists within the vault.

        Args:
            relative_folder_path (str): Vault-relative folder path to inspect or create.

        Returns:
            None: This function does not return a value.
        """
        full_path = self._get_folder_path(relative_folder_path)
        full_path.mkdir(parents=True, exist_ok=True)
        logger.info("Ensured folder exists: %s", sanitize_for_log(relative_folder_path))

    def delete_note(self, relative_path: str) -> bool:
        """Delete a note within the vault.

        Args:
            relative_path (str): Vault-relative note path to delete.

        Returns:
            bool: True when a file was deleted, False when it did not exist.
        """
        full_path = self._get_full_path(relative_path)
        if not full_path.exists():
            logger.warning(
                "Note not found for delete: %s", sanitize_for_log(relative_path)
            )
            return False
        if not full_path.is_file():
            raise ValueError("vault path is not a file")
        full_path.unlink()
        logger.info("Deleted note: %s", sanitize_for_log(relative_path))
        return True
