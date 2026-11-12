# Change notes (one file per pull request)

Every pull request used to add a line at the same place in `CHANGELOG.md`, so merging one
made the others conflict. Now each pull request adds **its own file here** instead, and
never edits `CHANGELOG.md`.

- File name: `<branch-short-name>.md`, for example `ui-widget-workspace.md`.
- Content: one heading (`### Added`, `### Changed`, or `### Fixed`) followed by bullets:

  ```markdown
  ### Added
  - `trader research snapshot`: live state per coin compared with history (ADR-029).
  ```

At release time, `uv run python scripts/build_changelog.py` folds every file here into the
`## [Unreleased]` section of `CHANGELOG.md` and deletes the files.
