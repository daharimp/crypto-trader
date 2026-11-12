# Tasks (one file per piece of work)

Every pull request used to add a section at the same place in `TASK.md`, so merging one made
the others conflict. New work now goes in **its own file here**; `TASK.md` keeps the history
up to 2026-11-12 and the "Discovered During Work" list.

- File name: `YYYY-MM-DD-short-topic.md`, for example `2026-11-12-notes-fragments.md`.
- Content: a title line with the date and who asked, then a checklist:

  ```markdown
  # 2026-11-12: Stop pull requests colliding on the notes files (owner request)

  - [x] Done item
  - [ ] Open item
  ```

Tick items in the same file when they are finished. To see everything still open:
`grep -rn "\- \[ \]" TASK.md tasks/`.
