# Domain Docs

This repository uses a single-context domain layout.

## Before exploring

Read:

- `CONTEXT.md`
- Relevant decisions under `docs/adr/`

If either location does not exist, proceed silently.

## Layout

```text
/
|-- CONTEXT.md
`-- docs/
    `-- adr/
```

## Vocabulary

Use terms exactly as defined in `CONTEXT.md`.

Do not substitute synonyms that the glossary explicitly rejects. If a required
concept is missing, reconsider whether it already exists under another name
before proposing a new term.

## Decisions

Architecture decisions belong under `docs/adr/`.

If proposed work contradicts an existing decision, identify the conflict
explicitly instead of silently overriding it.
