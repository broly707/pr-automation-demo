# Production Deployment Instructions

## Rollout strategy (recommended, low-risk order)

1. **Week 1 — Advisory mode.** Set `ai_review.fail_on_severity: "none"` and
   do **not** add `pr-automation/gate` to required status checks yet. The
   pipeline runs, comments, and generates/commits tests, but nothing blocks
   merges. This lets the team calibrate trust in the AI findings and test
   quality without risking a bad day blocking every PR.
2. **Week 2 — Enforce build/lint/tests only.** Add `pr-automation/gate` to
   required status checks, but keep `ai_review.fail_on_severity: "none"` so
   only build failures, lint failures, and test failures block merges (the
   uncontroversial, deterministic gates).
3. **Week 3+ — Enforce AI review.** Set `fail_on_severity: "critical"` (or
   `"high"` for stricter teams) once findings have been observed to be
   low-noise. Revisit the prompt templates in `config/review_prompts/` based
   on false positives the team has seen.

## Cost and rate-limit management

- `ai_review.max_diff_characters` and `max_characters_per_file` in
  `config/pipeline.yml` are the primary cost levers — they bound tokens sent
  per PR regardless of PR size.
- `test_generation.max_files_to_generate` bounds the number of Groq calls
  (and therefore cost + latency) for the test-generation stage per PR.
- Both `GroqClient` and `GitHubClient` retry transient failures (429/5xx)
  with exponential backoff (`config/pipeline.yml` → `*.max_retries`,
  `*.retry_backoff_base_seconds`) so brief rate-limit hits don't fail a PR
  outright.
- Monitor Groq usage from the Groq console; if the team's PR volume grows,
  consider lowering `max_files_per_request` / `max_files_to_generate` before
  raising them back up as budget allows.

## Caching (already configured, verify on rollout)

- **Gradle**: `gradle/actions/setup-gradle@v4` in `build.yml` and `lint.yml`
  caches `~/.gradle/caches` and the wrapper distribution automatically,
  keyed by lockfiles/build scripts.
- **Python**: `actions/setup-python@v5` with `cache: "pip"` in every job that
  installs `requirements.txt`, keyed by the hash of `requirements.txt`.
- **Swift Package Manager**: `actions/cache@v4` on
  `~/Library/Developer/Xcode/DerivedData`, keyed by `Package.resolved`, in
  both `build.yml` and `test-execution.yml`.

No action needed beyond initial rollout — caches populate on the first PR
and speed up every subsequent one automatically.

## Runner sizing

- Android jobs run on `ubuntu-latest` (GitHub-hosted, sufficient for typical
  Gradle assemble/test workloads). For very large monorepos, consider a
  self-hosted or larger GitHub-hosted runner via the `runs-on:` field in
  `build.yml` / `lint.yml` / `test-execution.yml`.
- iOS jobs require macOS runners (`macos-14`) — these are billed at a higher
  per-minute rate than Linux runners. `concurrency.cancel-in-progress: true`
  in `pr-orchestrator.yml` already prevents redundant runs from stacking up
  when a PR receives rapid successive pushes.

## Secret rotation

- `GROQ_API_KEY`: rotate via the Groq console, then update the repository
  secret. No code changes required.
- `GITHUB_TOKEN`: fully managed by GitHub Actions per-run; nothing to rotate.

## Monitoring the pipeline itself

- `docs/screenshots/pr-comment-example.md` shows the expected PR comment
  shape — use it as a reference when validating a new install.
- Every stage uploads its raw output as a workflow artifact
  (`build-status-*`, `lint-status-*`, `ai-review-report`,
  `generated-tests-manifest`, `test-results-*`,
  `pr-automation-final-report`) with 14–30 day retention, so a failed run
  can always be root-caused without re-running anything.
- If the pipeline itself needs debugging independent of a real PR, every
  script in `scripts/` runs standalone from a checked-out repo root with the
  right environment variables set (see README § Local development).

## Extending to additional platforms

To add a new platform (e.g. Flutter, React Native):
1. Add detection markers to `config/pipeline.yml` → `general`.
2. Add a `detect_project_type.py` output flag (`has_flutter`) and thread it
   through `pr-orchestrator.yml`'s `with:` blocks the same way
   `has_android`/`has_ios` are threaded today.
3. Add a new prompt template pair under `config/review_prompts/` and
   `config/test_prompts/`.
4. Add build/lint/test steps to the reusable workflows, guarded by the new
   `if: inputs.has_flutter` condition, following the existing Android/iOS
   job pattern in `build.yml`, `lint.yml`, and `test-execution.yml`.

No changes to `ai_code_review.py`, `generate_tests.py`, `aggregate_report.py`,
or `publish_pr_comment.py` are needed — they're already platform-generic and
driven by the `platform` field written into `changed_files.json`.
