# Notes for Claude Code

Cable Almanac is a Django web application for modeling and documenting the
cable infrastructure of buildings. It succeeds the private prototype in
`../smart-home-kabeldoku` (Pydantic models and YAML files, documented in
German, model reference in `docs/modell.md`), whose ideas and code are adopted
step by step.

## Layout

- `project/`: the Django project package (settings, URLs, WSGI/ASGI).
- `accounts/`: the custom user model.
- `inventory/`: all domain models and, at least initially, most of the
  remaining code.

## Conventions

- uv as package and project manager (`uv sync`, `uv add x`,
  `uv run manage.py …`).
- Everything in the repository is English: code, comments, docs and commit
  messages, in American spelling ("modeling").
- Strings in double quotes for user-facing text (labels, messages), in
  single quotes for everything technical (field names, choice values,
  keys). Docstrings use triple double quotes.
- `uv run ruff check` must pass. New code is formatted the way `ruff format`
  would format it, but existing code isn't reformatted. Comments, docstrings
  and long strings, which `ruff format` doesn't wrap, are wrapped by hand.
- Keep dependencies minimal; ask before adding new ones.
- Tests use Django's test framework (`uv run manage.py test`), one module
  per subject in the app's `tests/` package, named after category and subject,
  e.g. `inventory/tests/test_model_Component.py`.

## Guidelines

- Pragmatism over perfection: no speculative features without a concrete need.
- Make the smallest change that solves the problem. Mention unrelated
  cleanups instead of doing them.
- Use Django's own means before writing custom code or adding packages,
  e.g. the admin for editing data, forms for validating input, the auth
  views for login and logout.
- Views are function-based; class-based views only for trivial CRUD views.
- Comments, docstrings and commit messages explain what the code or diff
  doesn't: the why, rejected alternatives, pitfalls.

## Workflow

- After each step we review the diff and sometimes edit by hand. Re-read a
  file before changing it again; `git diff HEAD` shows the overall state.
- Commit only after the diff has been reviewed.
