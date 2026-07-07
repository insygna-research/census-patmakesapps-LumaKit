# Launch demo script — "Delegate a job. Approve from your phone."

The flagship loop in under 60 seconds: delegate from the browser, walk away,
approve the risky step from your phone, get the result. This is the GIF that
goes at the top of the README and in the Show HN post.

## What the demo proves

1. **Delegation, not chat** — you hand LumaKit a job and close the tab.
2. **Observability** — the web UI shows real tool activity while it works.
3. **Safe autonomy** — the protected step (a git commit) pauses the task and
   pings your phone; nothing dangerous runs without you.
4. **Cross-surface round-trip** — approve from Telegram, task completes, you
   get the result with a link to the shareable task page.

## Prerequisites (do these before recording)

- Backend running (`lumakit open`), Telegram configured, your chat = owner role.
- A demo workspace with an obvious, quick, *deterministic* job. Recommended
  seed: a small repo containing one failing unit test with an off-by-one bug
  (`tests/test_pricing.py` asserting `total_with_tax(100) == 108`, code says
  `* 1.08 + 1`). Fast to fix, visually clear diffs, and "commit the fix"
  naturally triggers the approval gate.
- Model: use a fast provider (e.g. `LLM_PROVIDER=anthropic`) so rounds are
  snappy on camera.
- Phone screen-mirroring ready (Windows Phone Link / scrcpy / QuickTime) so
  the Telegram approval is captured on the phone UI, not desktop Telegram.
- Do a full dry run first. Then delete the demo task and reset the repo
  (`git checkout . && git clean -fd` in the demo workspace) before recording.

## Shot list (~55s total)

| # | Duration | Shot | Action |
|---|----------|------|--------|
| 1 | 6s | Browser, Tasks view | Click **New Task**. Title: `Fix the failing test`. Goal: `Run the test suite, find the failing test, fix the bug, verify tests pass, then commit the fix with a clear message.` Submit. |
| 2 | 10s | Browser, task panel | Let the activity feed run: todo list appears, `run_command` (pytest, red), `read_file`, `edit_file` with the diff preview. This is the observability beat — hold long enough to read one diff line. |
| 3 | 4s | Browser | Tests re-run green in the feed. Then the task pauses: **Pending approval: git_commit** callout appears. Cut. |
| 4 | 8s | Phone (Telegram) | The ping is already there: task name, the exact command, `/approve 12` / `/deny 12` instructions. Show a beat of reading it. |
| 5 | 4s | Phone | Type `/approve 12`. Bot confirms the grant. |
| 6 | 8s | Browser or phone | Completion ping arrives: "Task complete" + result summary + task-page link. |
| 7 | 10s | Browser | Open the `/task/<id>` page from the link: status **done**, goal, result, todo list all checked, timeline. Slow scroll. |
| 8 | 5s | Title card | "LumaKit — delegate a job. Watch it work. Approve from your phone." + repo URL. |

## Narrative captions (overlay text, one per shot)

1. "Delegate a job from your desk"
2. "It works the job itself — you can watch, or walk away"
3. "Risky steps don't run without you"
4. "It reaches you where you are"
5. "Approve from your phone"
6. "…and it finishes the job"
7. "Every task leaves a shareable record"

## Recording notes

- 16:9, capture at 1080p minimum; GIF export ≤ 1200px wide, 12–15 fps,
  under 10 MB for the README (GitHub caches large GIFs poorly). Keep an MP4
  master for the blog post / HN comment.
- Suggested tools: OBS for capture; `gifski` for high-quality GIF encode.
- Dark theme, browser at 100% zoom, hide bookmarks bar, use a clean profile.
- The task id in `/approve <id>` must match what the ping says — read it from
  the message, don't hardcode from the dry run.
- If the model fixes the bug differently across takes, that's fine — the
  approval pause on `git commit` is the only beat that must land.
