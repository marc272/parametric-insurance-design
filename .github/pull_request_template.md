<!-- Title: [MAR-<n>] <Linear issue title>. One issue = one branch = one PR (AGENTS.md). -->

## Linear issue

MAR-<n>: <https://linear.app/marc-prinzing/issue/MAR-n>

## Summary

<!-- What changed and why, in a few lines. -->

## Acceptance criteria

<!-- Copy each criterion from the issue. Tick it only with evidence: a test name, command output or file. -->

- [ ] <criterion>: <evidence>
- [ ] CI is green on this PR

## Deviations from the issue

<!-- Anything done differently from the issue or the spec, and why. Write "None" if there are none. -->

## Follow-ups

<!-- Work you noticed but did not do, each with a one-line rationale. Proposed, not done. Write "None" if there are none. -->

## Checklist

- [ ] Only files this issue owns are changed (ADR 0002 ownership map)
- [ ] New third-party dependencies have a one-line justification above
- [ ] `core` and `viz` import no adapter; `packages/climada` does not import `packages/crc`
- [ ] No data beyond small test fixtures, and no credentials
- [ ] External-facing text follows the publication rule (AGENTS.md)
