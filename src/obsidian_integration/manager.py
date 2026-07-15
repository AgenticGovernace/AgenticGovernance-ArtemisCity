import os
from pathlib import Path


from ..utils.helpers import logger, sanitize_for_log


class ObsidianManager:
    """Provide the ObsidianManager abstraction used by this module."""

    def __init__(self, vault_path: str | None = None):
        # Re-read OBSIDIAN_VAULT_PATH at call time so tests that
        # monkeypatch src.mcp.config.OBSIDIAN_VAULT_PATH take effect.
        # A def-time default would freeze the original module-load value.
        if vault_path is None:
            from src.mcp.config import OBSIDIAN_VAULT_PATH as _vault

            vault_path = _vault
        self.vault_path = Path(vault_path)
        if not self.vault_path.is_dir():
            logger.error(
                "Obsidian vault path does not exist"
            )
            raise FileNotFoundError(f"Obsidian vault path not found: {self.vault_path}")
        logger.info(
            "Obsidian Manager initialized"
        )

    def _get_full_path(self, relative_path: str) -> Path:
        """Resolve a vault-relative path and reject vault escapes."""
        requested = Path(relative_path)
        if requested.is_absolute():
            raise ValueError("vault path must be relative")
        if ".." in requested.parts:
            raise ValueError("vault path must not contain '..' traversal")

        vault_root = self.vault_path.resolve()
        full_path = (vault_root / requested).resolve()
        try:
            full_path.relative_to(vault_root)
        except ValueError as exc:
            raise ValueError("vault path escapes configured vault root") from exc
        return full_path

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
        full_path = self._get_full_path(relative_path)
        full_path.parent.mkdir(parents=True, exist_ok=True)
        if overwrite:
            tmp_path = full_path.with_name(full_path.name + ".tmp")
            try:
                with open(tmp_path, "w", encoding="utf-8") as f:
                    f.write(content)
                os.replace(tmp_path, full_path)
            except Exception:
                try:
                    tmp_path.unlink()
                except FileNotFoundError:
                    pass
                raise
            logger.info(
                "Wrote note: %s (mode: w, atomic)", sanitize_for_log(relative_path)
            )
        else:
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
        full_path = self._get_full_path(relative_folder_path)
        if not full_path.is_dir():
            logger.warning("Folder not found: %s", sanitize_for_log(full_path))
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
        full_path = self._get_full_path(relative_folder_path)
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
            logger.warning("Note not found for delete: %s", sanitize_for_log(full_path))
            return False
        if not full_path.is_file():
            raise ValueError("vault path is not a file")
        full_path.unlink()
        logger.info("Deleted note: %s", sanitize_for_log(relative_path))
        return True
