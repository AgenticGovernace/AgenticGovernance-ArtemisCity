# Root Test Tree Status

The active pytest suite for Artemis City is `src/tests/`.

This root `tests/` tree is retained temporarily while the repository separation
work compares older tests against their `src/tests/` counterparts. Do not add
new tests here. New or migrated tests should go under `src/tests/`, matching the
root `pyproject.toml` and `Makefile` configuration.

Before deleting or archiving a file in this tree, compare it with the matching
file under `src/tests/` and migrate any behavior that is not already covered.
