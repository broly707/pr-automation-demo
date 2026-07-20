# Architecture

## Job graph

```
                         ┌────────┐
                         │ detect │
                         └───┬────┘
                 ┌───────────┼─────────────┬───────────────┐
                 ▼           ▼             ▼               ▼
          collect-changes  build          lint        (parallel)
                 │           │             │
        ┌────────┼───────┐   │             │
        ▼        ▼       │   │             │
   ai-review  test-gen   │   │             │
        │        │       │   │             │
        │        ▼       │   │             │
        │   (commits push)   │             │
        │        │       ▼   │             │
        │        └──► test-execution ◄─────┘ (needs build)
        │                    │
        └────────┬───────────┘
                  ▼
              reporting  (if: always())
                  ▼
                gate      (required status check)
```

Design intent: **build**, **lint**, and **ai-review** have no dependency on
each other and run fully in parallel — they're the three most expensive
steps and none needs the others' output. **test-generation** only needs the
changed-files manifest, so it also starts immediately after
`collect-changes` rather than waiting on build/lint. **test-execution**
waits on **build** (needs a working project, and on Android specifically
benefits from Gradle's warm dependency cache from the build job) and on
**test-generation** (needs the generated test files to exist and be
committed before running). **reporting** always runs (`if: always()`) so a
PR never gets stuck without feedback just because one earlier stage failed.

## Why reusable `workflow_call` workflows instead of one monolithic YAML

- Each stage (build / lint / ai-review / test-generation / test-execution /
  reporting) is independently testable, independently owned, and can be
  invoked from other workflows (e.g. a manual "re-run AI review only" trigger)
  without duplicating YAML.
- `pr-orchestrator.yml` stays small and declarative — it's the single place
  that defines *when* the pipeline runs and *how stages depend on each
  other*, with zero business logic of its own.
- Avoids the classic anti-pattern of copy-pasting the same 40 lines of
  Gradle/xcodebuild setup into five different jobs; that setup lives once
  per stage file.

## Why Python modules instead of inline `run:` scripting for the "smart" stages

Bash is fine for "run this CLI tool and check its exit code" (build, lint).
It's a poor fit for anything involving JSON parsing, HTTP calls with retry,
prompt templating, or file-tree manipulation (AI review, test generation,
reporting) — those stages are implemented as proper Python modules under
`scripts/`, unit-tested under `tests/scripts/`, importable, and independent
of GitHub Actions' YAML quirks. The workflow files call `python -m
scripts.<name>` and nothing more.

## SOLID in the script layer

- **Single Responsibility**: `github_client.py` only talks to GitHub.
  `groq_client.py` only talks to Groq. `config_loader.py` only loads YAML.
  `diff_utils.py` only shapes text. No module does two of these things.
- **Open/Closed**: adding a new static analysis tool means adding a step in
  `lint.yml` and a config entry — `record_status.py`'s status schema doesn't
  change. Adding a new platform (e.g. Flutter) means a new
  `detect_project_type.py` marker set and a new prompt template, not a
  rewrite of `ai_code_review.py`'s orchestration logic.
- **Liskov / Interface consistency**: `GroqClient.complete()` returns plain
  text regardless of whether it's producing JSON (review) or raw source code
  (test generation) — callers decide how to parse it, the client doesn't
  branch on caller intent.
- **Interface Segregation**: `GitHubClient` exposes narrow, purpose-built
  methods (`get_changed_files`, `upsert_pr_comment`, `create_check_run`)
  rather than a generic `request()` escape hatch that every caller has to
  understand GitHub's API shape to use.
- **Dependency Inversion**: every script reads its tunables from
  `config/pipeline.yml` via `config_loader.get_config()` rather than
  importing constants from each other — stages don't depend on each other's
  internals, only on the shared config contract and the artifact files they
  read/write.

## Why per-file and total character caps on the LLM prompt (performance requirement)

`diff_utils.build_diff_bundle()` enforces both `max_characters_per_file` and
`max_diff_characters` from config. This guarantees:
- We never send the whole repository — only the unified diff GitHub already
  computed for the PR.
- A single massive generated/vendored file changed by accident can't blow
  the whole prompt budget — it gets truncated with a clear marker instead.
- Total prompt size is deterministic and boundable, which bounds both cost
  and latency regardless of how large a PR is.

## Why a single `pr-automation/gate` check instead of requiring every job

Requiring five separate checks in branch protection is brittle — add a sixth
stage later and you have to remember to update the required-checks list, and
transient infra flakiness in any one of them blocks merges independently.
`gate` is the only job branch protection needs to know about; it fails if
`reporting` (which itself fails if any `fail_pipeline_on` stage failed or a
critical AI finding exists) didn't succeed. Everything else is an
implementation detail behind that one door.

## Why AI-generated tests are committed back instead of only posted as a diff/comment

Requirement #11 asks for automatic commits back into the PR branch "whenever
possible." "Whenever possible" matters because **forked-repository PRs**
receive a read-only `GITHUB_TOKEN` by GitHub design — pushing to a fork's
branch from the base repo's Actions run is not possible without the fork
owner's explicit cooperation. `commit_generated_tests.py` pushes when it can
(same-repo PRs, `pull_request` trigger with write permissions) and simply
uploads the generated files as a build artifact when it can't, rather than
failing the whole pipeline over a permissions boundary GitHub enforces for
security reasons.

## Why Groq (OpenAI-compatible endpoint) with a swappable client

`groq_client.py` is a ~100 line wrapper around one HTTP endpoint. Swapping
providers (e.g. to Anthropic's Claude API) means writing a new client with
the same `complete(system_prompt, user_prompt, ...) -> str` signature and
changing one import in `ai_code_review.py` / `generate_tests.py` — no
changes to prompt templates, config schema, or workflow YAML.
