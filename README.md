# PR Automation Pipeline

Production-grade GitHub Actions automation for Android (Kotlin) and iOS
(Swift) pull requests: build, static analysis, AI code review, AI-generated
unit tests, test execution, and a single consolidated PR report — with a
merge-blocking status check.

## What this does, on every `opened` / `synchronize` / `reopened` PR event

1. **Detects** whether the repo is Android, iOS, or both.
2. **Builds** the project (`assembleDebug` for Android, `xcodebuild` for iOS).
3. **Lints** it (ktlint + Android Lint + Detekt if configured / SwiftLint if configured).
4. **Reviews only the diff** with an LLM (Groq), focused on architecture, lifecycle,
   concurrency, null-safety, DI, security, and performance issues per platform.
5. **Generates real, compilable unit tests** (JUnit + MockK / XCTest) for changed
   source files that don't already have tests, and **commits them back to the PR branch**.
6. **Runs** both existing and newly generated tests.
7. **Publishes one consolidated markdown report** as a PR comment, and a
   **GitHub Check Run** (`pr-automation/gate`) that branch protection can require.
8. **Fails the pipeline** if build, lint, existing tests, generated tests fail,
   or the AI review finds a critical-severity issue.

## Folder structure

```
.github/workflows/
  pr-orchestrator.yml     # entry point - triggers on PR events, wires everything together
  build.yml               # reusable: Gradle assembleDebug / xcodebuild build
  lint.yml                # reusable: ktlint, Android Lint, Detekt, SwiftLint
  ai-code-review.yml      # reusable: sends diff to Groq, produces findings
  test-generation.yml     # reusable: generates + commits AI unit tests
  test-execution.yml      # reusable: runs existing + generated tests
  reporting.yml           # reusable: aggregates everything, publishes PR comment + check run

scripts/
  common/                 # shared library code (SOLID, no duplication across stages)
    config_loader.py      # loads config/pipeline.yml
    logger.py              # consistent logging across every script
    retry.py                # exponential backoff for transient failures
    github_client.py        # GitHub REST API wrapper (PR files, comments, check runs)
    groq_client.py          # Groq LLM client wrapper
    diff_utils.py            # diff truncation / prompt-size limiting
  detect_project_type.py   # Stage 2
  collect_changed_files.py # Stage 6
  ai_code_review.py        # Stages 7-8
  generate_tests.py        # Stage 9
  commit_generated_tests.py# Stage 11
  merge_status.py          # merges per-platform status files
  aggregate_report.py      # Stage 13 (report assembly)
  publish_pr_comment.py    # Stage 13 (publishing) + Stage 14/15 (gate)
  record_status.py         # CLI used by workflow shell steps to log stage results

config/
  pipeline.yml             # ALL tunables live here - models, thresholds, paths, limits
  review_prompts/          # AI code review prompt templates (Android / iOS)
  test_prompts/            # AI test generation prompt templates (Android / iOS)

tests/scripts/             # unit tests for the automation scripts themselves
docs/                      # architecture, setup, deployment docs
```

## Quick start

1. Copy `.github/`, `scripts/`, `config/`, and `requirements.txt` into your
   Android/iOS monorepo (or Android-only / iOS-only repo — the pipeline
   auto-detects and skips what doesn't apply).
2. Add two repository secrets (Settings → Secrets and variables → Actions):
   - `GROQ_API_KEY` — your Groq API key.
   - `GITHUB_TOKEN` is automatic; no action needed, but confirm workflow
     permissions are set to "Read and write" (Settings → Actions → General).
3. (iOS only) Add a repository **variable** `IOS_SCHEME` with your Xcode
   scheme name if it isn't `App`.
4. Add `pr-automation/gate` to your branch protection rule's required status
   checks (Settings → Branches → Branch protection rules → your default branch).
5. Open a PR. The pipeline runs automatically.

See `docs/SETUP_GUIDE.md` for the full walkthrough and `docs/ARCHITECTURE.md`
for design rationale.

## Local development

```bash
pip install -r requirements.txt
python -m pytest tests/ -q
```

Every script can also be run standalone from a repo root for debugging,
e.g.:

```bash
GITHUB_TOKEN=... PR_NUMBER=42 HEAD_SHA=... HEAD_REF=... BASE_REF=main \
  python -m scripts.collect_changed_files
```

## Configuration

Nothing is hardcoded. All models, thresholds, paths, and limits live in
[`config/pipeline.yml`](config/pipeline.yml). Prompt templates live in
`config/review_prompts/` and `config/test_prompts/` so prompt tuning never
requires touching Python.
