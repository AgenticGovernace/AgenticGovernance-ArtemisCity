import os
from pathlib import Path
from mcp.config import OBSIDIAN_VAULT_PATH
from utils.helpers import logger


class ObsidianManager:
    def __init__(self, vault_path: str = OBSIDIAN_VAULT_PATH):
        self.vault_path = Path(vault_path)
        if not self.vault_path.is_dir():
            logger.error(f"Obsidian vault path does not exist: {self.vault_path}")
            raise FileNotFoundError(f"Obsidian vault path not found: {self.vault_path}")
        logger.info(f"Obsidian Manager initialized for vault: {self.vault_path}")

    def _get_full_path(self, relative_path: str) -> Path:
        """Constructs the full path within the vault."""
        return self.vault_path / relative_path

    def read_note(self, relative_path: str) -> str | None:
        """Reads the content of an Obsidian note."""
        full_path = self._get_full_path(relative_path)
        if not full_path.is_file():
            logger.warning(f"Note not found: {full_path}")
            return None
        with open(full_path, "r", encoding="utf-8") as f:
            content = f.read()
            logger.debug(f"Read note: {relative_path}")
            return content

    def write_note(self, relative_path: str, content: str, overwrite: bool = True):
        """Writes content to an Obsidian note. Creates directories if necessary."""
        full_path = self._get_full_path(relative_path)
        full_path.parent.mkdir(parents=True, exist_ok=True)
        mode = "w" if overwrite else "a"  # 'w' for overwrite, 'a' for append
        with open(full_path, mode, encoding="utf-8") as f:
            f.write(content)
            logger.info(f"Wrote note: {relative_path} (mode: {mode})")

    def list_notes_in_folder(
        self, relative_folder_path: str, suffix: str = ".md"
    ) -> list[str]:
        """Lists all notes (Markdown files) in a specified folder."""
        full_path = self._get_full_path(relative_folder_path)
        if not full_path.is_dir():
            logger.warning(f"Folder not found: {full_path}")
            return []
        notes = [
            str(f.relative_to(full_path))
            for f in full_path.iterdir()
            if f.is_file() and f.suffix == suffix
        ]
        logger.debug(f"Listed {len(notes)} notes in {relative_folder_path}")
        return notes

    def create_folder(self, relative_folder_path: str):
        """Ensures a folder exists within the vault."""
        full_path = self._get_full_path(relative_folder_path)
        full_path.mkdir(parents=True, exist_ok=True)
        logger.info(f"Ensured folder exists: {relative_folder_path}")
