import pytest

from src.obsidian_integration.manager import ObsidianManager


@pytest.fixture
def manager(tmp_path):
    vault = tmp_path / "vault"
    vault.mkdir()
    return ObsidianManager(vault_path=str(vault))


def test_nested_relative_paths_are_allowed(manager):
    manager.write_note("notes/projects/example.md", "hello")

    assert manager.read_note("notes/projects/example.md") == "hello"
    assert manager.list_notes_in_folder("notes/projects") == ["example.md"]
    assert manager.delete_note("notes/projects/example.md") is True
    assert manager.read_note("notes/projects/example.md") is None
    assert manager.delete_note("notes/projects/example.md") is False


@pytest.mark.parametrize(
    "path",
    [
        "/tmp/outside.md",
        "../outside.md",
        "notes/../../outside.md",
    ],
)
def test_rejects_absolute_and_traversal_paths(manager, path):
    with pytest.raises(ValueError):
        manager.read_note(path)

    with pytest.raises(ValueError):
        manager.write_note(path, "blocked")

    with pytest.raises(ValueError):
        manager.list_notes_in_folder(path)

    with pytest.raises(ValueError):
        manager.create_folder(path)

    with pytest.raises(ValueError):
        manager.delete_note(path)


def test_rejects_resolved_sibling_paths(tmp_path):
    vault = tmp_path / "vault"
    sibling = tmp_path / "sibling"
    vault.mkdir()
    sibling.mkdir()
    (vault / "linked").symlink_to(sibling, target_is_directory=True)

    manager = ObsidianManager(vault_path=str(vault))

    with pytest.raises(ValueError):
        manager.write_note("linked/escape.md", "blocked")


@pytest.mark.parametrize(
    "path",
    ["notes/./alias.md", "notes//alias.md", "notes/alias.md/", r"notes\alias.md"],
)
def test_rejects_noncanonical_path_aliases(manager, path):
    """Derived files cannot collapse multiple SQL identities onto one target."""
    with pytest.raises(ValueError, match="canonical"):
        manager.write_note(path, "blocked")


def test_rejects_symlink_alias_inside_vault(tmp_path):
    """An in-vault symlink cannot bypass the canonical SQL path fence."""
    vault = tmp_path / "vault"
    notes = vault / "notes"
    vault.mkdir()
    notes.mkdir()
    (vault / "alias").symlink_to(notes, target_is_directory=True)
    manager = ObsidianManager(vault_path=str(vault))

    with pytest.raises(ValueError, match="canonical"):
        manager.write_note("alias/task.md", "blocked")
