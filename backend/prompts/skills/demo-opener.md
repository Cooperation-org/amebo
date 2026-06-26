---
name: demo-opener
description: Decide whether a small demo artifact built in the target's own ecosystem could open or advance a conversation — and if so, scope the smallest one and draft it as a task. Use for "could we build a quick demo for X", "what demo would catch their interest", "how do we open this conversation".
---
Because demos are cheap to make now, one of our strongest moves is to build a
tiny artifact inside the target's own ecosystem (their stack, their data shape,
their problem) that catches interest and moves the conversation one step.
Sometimes that's exactly right; often it isn't. Judge honestly.

## What to do
1. **Ground in the overlap.** What is the target actually doing (their
   ecosystem-research findings or CRM/abra context) and what do we have that's
   relevant (our repos, LinkedClaims / Amebo capabilities, prior demos in abra)?
   A good demo sits where their problem meets our stuff.
2. **Decide IF a demo fits.** It fits when they want adoption in their ecosystem,
   are actively building something, or a small artifact would make concrete a
   value that words won't. It does NOT fit when the relationship is too cold, the
   ask is unclear, or a demo would feel presumptuous — say so and recommend
   against it.
3. **If it fits, scope the SMALLEST artifact** that opens or advances one step.
   A static HTML demo is a great pattern here (fast, honest, no throwaway
   backend). Name what it shows, in whose ecosystem, and the conversation step it
   unlocks.
4. **Draft it as a Taiga task** (gated, with a due date and a cash tag): clear
   scope, who it's for, what it should demonstrate.

## Output
A yes/no on whether a demo fits and why; if yes, the smallest demo scoped (what
it shows + which ecosystem + the next step it opens) and the drafted task.

## Don't
- Don't propose a demo just because we can — recommend against it when it doesn't fit.
- Don't scope a big build; smallest-thing-that-opens-the-door.
- Static/throwaway demo HTML is fine; never a hacky production shortcut.
