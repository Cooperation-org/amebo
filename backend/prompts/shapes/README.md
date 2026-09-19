# Shapes

A shape is the form of what a person receives or works on, not what it is
about. It is high level, like a pattern: the same shape carries a sales digest,
a research sweep, or a week's goals. A skill says how to do a kind of work; a
shape says what the result looks like and how a person interacts with it.

Three levels, named on purpose (project owner, 2026-09-19):

| level | what it is | where |
|---|---|---|
| **shape** | a high-level pattern of the description of things | `prompts/shapes/` |
| **skill** | a capability with knowledge; how to do a kind of work | `prompts/skills/` |
| **implementation skill** | precise, step by step, for one tool or repo | with that tool (a repo's docs, a Claude Code skill) |

Each file is self-contained markdown with frontmatter (`name`, `description`),
so any agent or person can read it without amebo. Amebo lists shapes in the
system prompt and loads one with `load_shape(name)`. An org's own shapes go in
`<context repo>/shapes/` and shadow these by filename.

Where a person's own words go: their words about *what they are aiming at*
or *how to talk to them* are a **statement** (`docs/STATEMENTS.md`), pointed at
where the words live (abra, a doc), quoted verbatim into every prompt. A
**rule** in `rules.md` is the always-on distillation and cites them. A
**shape** quotes the words that define that form. A **skill** quotes the words
that define that procedure. Nothing paraphrases them.

Every output to a person takes a shape. Default `one-line`. Many things: `map`.
Needing a decision: `question`. Something to hand over or print:
`evidence-document`. Anything with a date coming: `before-an-event`.
