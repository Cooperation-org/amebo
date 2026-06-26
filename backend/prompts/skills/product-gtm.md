---
name: product-gtm
description: Run the multi-step go-to-market for one product or experiment — define the customer archetype, find people/companies that fit, draft messaging, choose a channel (sequence vs. a reviewer), then loop on feedback until someone actually TRIES it. Use for "market <product>", "who's the customer for <product>", "get someone to try <product>".
triggers:
  - "market this product"
  - "go to market for"
  - "who is the customer for"
  - "get someone to try"
  - "customer archetype"
---
We have several products/experiments (the talent/resume tools, etc.) where people
say nice things but no one has really *used* it yet. The goal of this skill is not
buzz — it's getting a real person to actually try the product, then honing until
that happens. Treat it as a time-boxed experiment with a tracked result (the
projects-repo MINI/MAIN doc), not a campaign that runs forever.

## What to do
1. **Ground in the product first.** Read its experiment/project doc (Motivation,
   Outcome, Target Audience, Results) and what it actually does. If it has no
   defined target audience yet, that IS step one — don't skip to outreach.
2. **Define the customer archetype** sharply: who feels the pain this solves —
   their role, context, what they're trying to do, where they spend time. One
   sharp archetype beats a vague "everyone."
3. **Find fits.** Look in our network first (CRM via contact/lead search, abra)
   for people/companies matching the archetype. Name concrete criteria for finding
   more outside — amebo has no open-web search, so hand the human search criteria
   rather than fabricating names. For where-they-are, load `ecosystem-research`.
4. **Draft the messaging** in our own voice, specific to the archetype and their
   pain — never generic (no slop). Amebo has no email-send channel wired, so this
   produces drafts + a plan; it does NOT auto-send a drip.
5. **Choose the channel honestly:** a short outreach sequence to fitted
   individuals, OR — often higher-yield for us — getting one credible reviewer /
   writer / influencer to actually try it and talk about it (load `find-reviewer`).
   Cold drip campaigns are low-yield for us; prefer real participation in the
   archetype's spaces.
6. **Close the loop.** The metric is a real trial, not a like. Capture what people
   actually say, feed it back into the archetype + messaging, record the result in
   the experiment doc, and draft the next steps as gated Taiga tasks (due + cash).
   Keep honing until someone genuinely tries it — then write up what worked.

## Output
The archetype in 2-3 lines, a short list of real fits from our network + criteria
for finding more, the drafted messaging, the chosen channel + why, and the gated
next-step task(s).

## Don't
- Don't market to "everyone"; one sharp archetype.
- Don't claim it auto-sends a drip — no email channel; drafts + plan only.
- Don't optimize for buzz over a real trial; don't generate slop messaging.
- Record results in the experiment doc; don't let a campaign run unbounded.
