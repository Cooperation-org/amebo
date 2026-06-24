---
name: make-skill
description: Create or edit an amebo skill. Use when the user says they want to make / add / change an amebo skill, or are explaining how amebo should handle a recurring kind of request.
triggers:
  - "amebo skill"
  - "make a skill"
  - "making a skill"
  - "create a skill"
  - "new skill"
  - "edit a skill"
---
The user wants to author or edit an amebo skill. Help them turn what they say into a clean skill.

## What to do
1. Call `load_skill('_template')` to get the skill template and its drafting instructions, and follow them.
2. Let the user explain at length — they may think out loud. Don't transcribe; distill.
3. Draft the skill as a markdown file body for `prompts/skills/<kebab-name>.md`: a sharp one-line `description` (this drives selection), then short intent + only the non-obvious decisions, output shape, and don'ts. Intent over micro-steps.
4. Show the full draft back for approval before it's saved. Ask if their intent is unclear — never invent it.

## Output
The proposed skill file (frontmatter + body), ready to drop into `prompts/skills/`.

## Don't
- Don't pad with keystroke-level steps or generic advice the model already knows.
- Don't save/commit it yourself — you can't write the repo; present the draft so an operator saves it.
