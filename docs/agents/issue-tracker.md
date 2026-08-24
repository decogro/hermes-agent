# Issue tracker: GitHub

Issues and specifications for this repository live in GitHub Issues.

The personal fork is `decogro/hermes-agent`. The upstream repository is
`NousResearch/hermes-agent`.

Use the `gh` CLI for issue operations after the fork is configured as `origin`.

## Conventions

- Create: `gh issue create --title "..." --body "..."`
- Read: `gh issue view <number> --comments`
- List: `gh issue list --state open`
- Comment: `gh issue comment <number> --body "..."`
- Label: `gh issue edit <number> --add-label "..."`
- Close: `gh issue close <number> --comment "..."`
- Infer the repository from the current Git remote.

## Pull requests as a triage surface

PRs as a request surface: no.

## Skill instructions

When a skill says "publish to the issue tracker," create a GitHub issue.

When a skill says "fetch the relevant ticket," run:

`gh issue view <number> --comments`

## Wayfinding operations

Used by `/wayfinder`. The map is a single issue with child issues as decision
tickets.

- **Map**: create one issue labelled `wayfinder:map`.
- **Child ticket**: create an issue labelled `wayfinder:research`,
  `wayfinder:prototype`, `wayfinder:grilling`, or `wayfinder:task`, then link it
  to the map through GitHub's sub-issues endpoint. If sub-issues are unavailable,
  put `Part of #<map>` in the ticket and list it as a task in the map.
- **Blocking**: use GitHub's native issue-dependency endpoint. If native
  dependencies are unavailable, put `Blocked by: #<ticket>` in the body.
- **Frontier**: open, unassigned child tickets with no open blockers.
- **Claim**: `gh issue edit <number> --add-assignee @me` before working it.
- **Resolve**: post the decision as a comment, close the ticket, then add a
  one-line linked gist to the map's Decisions-so-far section.
