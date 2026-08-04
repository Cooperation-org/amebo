# UX principles

Golda's rules for anything a person looks at. Same file in `amebo`, `workers.vc`
and `govkit` — one set of rules, three repos. Quoted lines are her words.

Judge every change by what the person experiences first. If a change is smooth,
clean, fast and easy, it is right; if it adds a click, a redirect, a dead end or
a paragraph, it is not.

---

## 1. Show, don't tell

> "SHOW not tell — if it did something useful SHOW me and let me correct it or
> do something with it. NEVER textwall at me about what amebo did."

Show the thing. Never a report about the thing. If the agent drafted an email,
the email is on screen, editable. If it found a link, the link is on screen.
No digest of its own activity, no "drafted and waiting", no summary of work done.

## 2. Everything actionable

> "make eveything i see editable or actionable"

Nothing on screen exists only to be read. Every element is a thing you can press,
follow, or change.

## 3. Links

> "LINKS to the things, previews, brief, as links, not 'drafted and waiting'
> that is so sycophantic and annoying just THE THINGS"

If it cannot be shown, link it. `#34 Apply: NCBA IMPACT 2026 ↗`, not "the task
has been created for you."

## 4. If I can see it, I can edit it

> "everything i see, can edit, quick not too many clicks"

Every visible field is editable where it sits, whenever the source system allows
it at all. A read-only line next to editable ones is a bug. Use the real control:
a status is a dropdown of that board's own statuses, an assignee is a dropdown of
that board's own members — never a free-text box that fails on a typo.

## 5. Omit needless words

Be concrete, be precise, cut the rest. No labels that restate the obvious, no
helper prose, no preamble.

**Banned outright:** "we don't just X, we Y" · "not just… but" · dramatic
em-dash reveals · empty intensifiers (lived, credible, concrete, powerful) ·
clipped comma-spliced fragments ("six quote slots, yours, article can't ship").

> "if i have to see ai'isms like this ... i will NEVER USE THIS TOOL"

## 6. Save in the flow

> "save easily and in the flow"

Edit in place, save on leaving the field. No edit mode, no Save button to hunt
for. Offer an explicit Save anyway for people who would rather press something.

## 7. Their words lead

> "in the needs thing it should have QUOTES from the user and a LINK to where
> they asked. elevate the HUMAN words"

Lead with what a person actually said, named, with a link to where they said it.
`Peter: ok dns is ready on my side ↗` — name, colon, their words. Never an
indented block quote with an attribution line underneath.

## 8. The agent is invisible

> "tell amebo to mostly be invisible, shut it up! ai's are SUPER ANNOYING when
> they textwall"

## 9. Assembling beats writing

> "helper does not always have to write words for me sometimes its just
> assembling the context and links conveniently"

Most of the time the contribution is the quote, the task, the link and the file
gathered in one place. Generating text is the exception.

## 10. Don't box it in

> "i hate the idea of being limited but it might be good to have a task take up
> most of screen when popped up"

When something opens, give it room — most of the screen, one key to leave. A
cramped inline strip is worse than a link out.

## 11. Mark what was found, say what is invented

> "if amebo found it put like (?) and if it was in the ticket leave out (?)"

A link already on the record stands plain. A link the agent went and found gets
`(?)`, so the reader knows which to distrust. Mock data in a mockup is labelled
as mock, on the page. A plausible fake quote attributed to a real colleague is
worse than an empty box.

## 12. Fail forward, never a dead end

No redirect chains, no 404 where a forward would do. A page that has been folded
into another forwards into it.

## 13. Later needs a when

> "We're snoozing the task, not snoozing the claw."

Dismissing is not deciding. Pushing something out writes a new date on the thing
itself, so it comes back on its own. No snooze state in the agent.

## 14. Deadlines raise rank, they don't get their own box

> "it can be mixed just deadlines are like increase the ranking"

One ranked list. Say which half of the ranking put each item where it is: a rule
(dated, deterministic, needs no defending) or a judgement (which must show its
reason).

## 15. High guards on acting alone

> "if its clear what to do, it can just do it, but if it involves communicating
> with a human in slack or anything possibly destructive, it should check"

Acts alone: reversible, touches no person. Always asks: anything a human will
read, anything destructive, anything it is guessing at. A human pressing the
button is not the agent acting alone — do not gate that.

---

## 0a. Never hand a person a generic task

> "do not ever assign generic patterns as tasks. tasks are specific, thought
> must be invested to make them actionable and prioritized and have useful data.
> thought must go into a task before you share it with a human. don't slop at
> humans! The WHOLE POINT of ai is SAVE HUMANS TIME. not slop at them waste
> human time."

Anything put in front of a person carries the thinking already done. Before it
reaches a list it has, in itself:

- **The specific thing, named.** "Land and have meeting with client" is a
  category, not a task. Which client, asked for what.
- **The link that lets them act** — profile, doc, form, thread. If there isn't
  one, finding it *is* the work.
- **The context that saves the lookup** — who, where it came from, what was
  already said, what happens next.
- **Why now** rather than later.

Cannot fill those in? Do not offer it. Handing over a half-formed task spends
the person's time instead of saving it, which is the opposite of the point.
Same rule for a list, a digest, a Slack ping, a suggestion.

---

## 0. Look it up. Do not invent a pattern.

> "find GOOD UX GUIDELINES AND REFER TO THEM. THAT IS THE MOST IMPORTANT THING
> EVER."

Before building any interface element — a dialog, a form, an autosave, a date
picker, an empty state, a list, an error — open one of these and follow what it
says. They are the standard. Nothing here overrides them; the rules below are
what Golda wants on top of them.

| Look up | Where |
|---|---|
| Is this interface usable at all | [Nielsen's 10 usability heuristics](https://www.nngroup.com/articles/ten-usability-heuristics/) and the [NN/g article library](https://www.nngroup.com/articles/) |
| How a component should behave | [Material Design 3](https://m3.material.io/) and [Apple Human Interface Guidelines](https://developer.apple.com/design/human-interface-guidelines) |
| Keyboard, focus, screen readers | [WAI-ARIA Authoring Practices](https://www.w3.org/WAI/ARIA/apg/patterns/) — the dialog pattern is not optional |
| Wording on screen | [GOV.UK content style guide](https://www.gov.uk/guidance/style-guide) and [GOV.UK Design System](https://design-system.service.gov.uk/) |
| Contrast, targets, motion | [WCAG 2.2](https://www.w3.org/WAI/WCAG22/quickref/) |

Cite which one you followed in the commit or the PR. "I thought it looked
better" is not a reason. If the guidelines disagree with each other, say so and
ask.

**The product never explains itself.** No "saves as you leave a field", no
helper sentence under a box, no tooltip teaching the user your model. Copy that
explains the product means the design failed. Look up how the standard pattern
shows that state and use that instead.

---

## Working this way

- **Show a design, don't describe one.** "this is why i needed to SEE it. your
  conception of words and mine are completely different." Build the picture,
  put it on a URL, then talk.
- **Proposals before builds** when the shape is not settled.
- **Never invent an element and show it as real.** Say which parts do not exist.
- **Questions in concrete terms, 50 words or less, no internal labels.** "if you
  dont' really know what you mean" you cannot ask it plainly.
- **Answer the question that was asked.**

Longer draft with the full session history:
`~golda/work/7-25-2026-how-to-design-together.md`. Worked example:
`demos.linkedtrust.us/claw-list-proposals/`.
