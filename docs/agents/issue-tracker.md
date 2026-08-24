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
