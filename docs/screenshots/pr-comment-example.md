# Example: Rendered PR Comment (reference mockup)

> This file is a text mockup of what the published PR comment looks like
> once rendered by GitHub — used for onboarding/QA reference since actual
> screenshots depend on a live repository.

---

**PR Automation Report — ❌ FAIL**

_Generated 2026-07-14 09:12 UTC · total pipeline time ~187s_

## Summary

| Stage | Status | Detail |
|---|---|---|
| Build | ✅ PASS | Android assembleDebug (Gradle) |
| Lint | ✅ PASS | ktlint: pass. Android Lint: pass. Detekt: pass. |
| Existing Tests | ✅ PASS | Gradle testDebugUnitTest |
| Generated Tests | ❌ FAIL | AI-generated tests executed as part of testDebugUnitTest |
| AI Review (critical gate) | ❌ FAIL | 1 finding(s) across Android/iOS |

## Files Reviewed

- `app/src/main/kotlin/com/example/auth/LoginViewModel.kt` (android, modified)
- `app/src/main/kotlin/com/example/auth/AuthRepository.kt` (android, modified)

## Issues Found & Suggested Fixes

### Android

The diff introduces a ViewModel that launches a coroutine on `GlobalScope`
instead of `viewModelScope`, which leaks the coroutine past the ViewModel's
lifecycle.

| Severity | Category | File | Issue | Suggested Fix |
|---|---|---|---|---|
| 🔴 critical | coroutines | `LoginViewModel.kt:34` | `GlobalScope.launch` used for a network call tied to UI state | Replace with `viewModelScope.launch { ... }` so the coroutine is cancelled automatically on `onCleared()` |

## AI-Generated Tests

| Source File | Generated Test File | Platform |
|---|---|---|
| `app/src/main/kotlin/com/example/auth/AuthRepository.kt` | `app/src/test/kotlin/com/example/auth/AuthRepositoryTest.kt` | android |

## Build / Lint / Test Status

### Build: ✅ PASS
Android assembleDebug (Gradle)

### Lint: ✅ PASS
ktlint: pass. Android Lint: pass. Detekt: pass.

### Existing Tests: ✅ PASS
Gradle testDebugUnitTest

### Generated Tests: ❌ FAIL
`AuthRepositoryTest.kt` fails to compile: unresolved reference `mockk` — module missing MockK dependency.
