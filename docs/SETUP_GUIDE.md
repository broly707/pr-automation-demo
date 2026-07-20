# Setup Guide

## 1. Prerequisites

- An Android repo (Gradle, with a checked-in `gradlew` wrapper), an iOS repo
  (Xcode project or workspace), or a monorepo with both.
- A [Groq](https://console.groq.com) account and API key.
- Admin access to the GitHub repository (to set secrets, variables, and
  branch protection).

## 2. Copy the pipeline into your repo

Copy these paths from this deliverable into the root of your target repository:

```
.github/workflows/
scripts/
config/
requirements.txt
```

(`docs/`, `README.md`, and `tests/` are optional but recommended to keep.)

## 3. Configure repository secrets

Settings → Secrets and variables → Actions → **New repository secret**:

| Name | Value |
|---|---|
| `GROQ_API_KEY` | Your Groq API key |

`GITHUB_TOKEN` is provided automatically by GitHub Actions — do not create
it manually. Confirm write access is enabled:

Settings → Actions → General → Workflow permissions → **Read and write permissions**.

This is required for:
- `test-generation.yml` to push the AI-generated test commit.
- `reporting.yml` to post/update the PR comment and create the check run.

## 4. Configure repository variables (iOS only)

Settings → Secrets and variables → Actions → Variables tab → **New repository variable**:

| Name | Value |
|---|---|
| `IOS_SCHEME` | Your Xcode scheme name (defaults to `App` if unset) |

## 5. Adjust `config/pipeline.yml` for your project layout

Key values to check before your first PR:

- `android.assemble_task`, `android.unit_test_task` — must match real Gradle
  task names in your project (they usually do out of the box for a standard
  `com.android.application` module).
- `android.main_source_set` / `android.test_source_set` — must match your
  actual source set layout if you use a non-standard Kotlin source layout.
- `ios.scheme`, `ios.destination` — the simulator destination must match a
  simulator runtime available on GitHub's `macos-14` runner image (check
  [actions/runner-images](https://github.com/actions/runner-images) release
  notes if you need a different iOS version).
- `ai_review.fail_on_severity` — set to `"none"` if you want AI review to be
  advisory-only at first, then tighten once the team trusts the findings.
- `test_generation.max_files_to_generate` — cap on how many files get an
  AI-generated test per PR, to bound cost/latency on large PRs.

## 6. (Optional) Add Detekt / SwiftLint configuration

- Detekt: add `config/detekt/detekt.yml` (path is configurable in
  `pipeline.yml` under `android.detekt_config_path`). If this file is
  absent, `lint.yml` automatically skips Detekt without failing the build.
- SwiftLint: add a `.swiftlint.yml` at the repo root. If absent, SwiftLint is
  skipped without failing the build.

## 7. Enable branch protection

Settings → Branches → Add branch protection rule (for your default branch,
typically `main`):

- ✅ Require status checks to pass before merging
- Search for and select **`PR Automation Gate / PR Automation Gate`**
  (the `gate` job in `pr-orchestrator.yml`) — this is the only check you
  need to require; it reflects the pass/fail of every stage underneath it.
- ✅ Require branches to be up to date before merging (recommended)

## 8. Open a test PR

Push a small Kotlin or Swift change on a branch and open a PR against your
default branch. Within a few minutes you should see:

- A single PR comment titled **"PR Automation Report"** with a PASS/FAIL
  banner, per-stage status table, AI review findings, and a table of any
  AI-generated test files.
- If eligible source files changed, a new commit on your PR branch adding
  `*Test.kt` / `*Tests.swift` files (author: `pr-automation-bot`).
- A **check run** named `pr-automation/gate` on the PR's checks tab.

## 9. Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `GROQ_API_KEY is not set` in AI review/test-gen logs | Secret not configured or misspelled | Re-check step 3, secret name must be exact |
| Test-generation runs but no commit appears | PR is from a fork | Expected — see `docs/ARCHITECTURE.md` § forked PRs. Generated files are still available as a workflow artifact. |
| `gate` check never appears in the branch protection search box | It hasn't run once yet on this repo | Open one PR first so GitHub learns the check name, then add it to the required list |
| Android build fails with "Permission denied: ./gradlew" | Wrapper isn't executable in git | Workflow already runs `chmod +x ./gradlew`; verify `gradlew` is committed to the repo |
| iOS build can't find scheme | `IOS_SCHEME` variable not set / wrong name | Set the repository variable from step 4 |
