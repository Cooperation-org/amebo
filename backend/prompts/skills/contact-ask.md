---
name: contact-ask
description: For one CRM card or contact, work out exactly what the opportunity is, the one concrete thing to do, and the one ask that is relevant to that person and worth their time. Use on a research row, a contact reached from research, or any card where it is not clear what to do.
---
Project owner: "what is the thing to DO?" · "dive deeper into what exactly is opportunity or ask" · "how make best use of their time, what we ask that is ACTUALLY RELEVANT to them" · "there has to be really critical steps not just throw everything at the fan."

Project owner: "we don't have to have a product. we also just want to subcontract or do work. we want to get part of this work." Not having a product never fails a card. A firm already selling this may be the best way in: who is short of people and could hand us part of it?

Being listed on a research row means only that a person's employer matched a topic. It is not an opportunity. The default answer is "no ask". A weak ask spends a person's goodwill, so finding none is a good result.

## Steps, in order. Stop at the first that fails and say so.
1. **The latest note is the request.** Answer that. If it names a person, work on that person. Earlier notes are the conversation; use them.
2. **Who they are now.** Current role, what they decide, what they know, from the CRM, abra (`abra search`, `abra about`) and the web. LinkedIn pages can't be read: search the name and employer. Also how we know them, from evidence only: messages, meetings, or a LinkedIn connection with nothing behind it. If you can't verify their role, stop.
3. **What of ours matters to their job.** Read our projects in `Active/<slug>/MAIN.md`. Name the project and the thing it does, or the work our engineers could do for them: a subcontract, a build, extra hands against a deadline. For that, find evidence they buy or need outside work: open roles, partner or delivery programs, a tender, a stated deadline, recent funding. Compare it to this person's own work, not to the row's topic or their employer's size. No match: no ask.
4. **What they get.** Something useful to them, in their terms, this quarter. If only we benefit, no ask.
5. **The smallest ask.** One thing: one question only they can answer, or one named introduction with a reason, or one small decision. Say why this person and not someone else at their organization. A call is not an ask unless you can say what it decides.
6. **Who pays and for what.** On a row with a dollar figure: the named buyer, what they would buy from us, and whether the number has a source or is an estimate. No named buyer means the number is a guess: say so.
7. **Ethics.** Value aligned and ethical only. Never the US Department of Defense, DHS, CBP, Border Patrol or ICE, including through a contractor. If this touches them: no ask, and say why.

8. **Who can introduce us.** Project owner: "if there is opportunity then you look thru my contacts to see if we have a partner intro." Opportunity first, then people. Search the contacts (`abra who`, `abra search`, the CRM through `amebo-elm GET /api/search?q=`) for someone at the firm, or who works with it. Name them and the evidence: messages or meetings, not a LinkedIn connection alone. None found: say so.
8a. **The onramp.** Project owner: "we have capability but we need like a more specific onramp, message or artifact it has to be CONCRETE." · "these are valuable contacts but i don't want to randomly spam them." Name the one thing that makes contact worth their attention: an artifact we can show (what it is, what real data of theirs or their market it uses, what we have today, how many hours to finish it), or a fact they would want to know. "We have capability" is not an onramp. Without one: nothing goes out, and say what would have to exist first.
9. **Judge it, then do it again.** Read your answer as this person, busy, on the day it arrives. Is it spam? Would they reply, and why? What would they already know, or have built themselves? Look up whatever could prove it wrong, then rewrite or reject. Repeat until it survives, three rounds at most. What does not survive is "no ask".

Every answer then goes to a separate review (`contact-ask-review.md`) before it reaches the card.

## Output, under 250 words, as plain lines
- **Do:** the one concrete next thing, or "Nothing yet" with what is missing.
- **Pathways:** up to 3 ways we could work with them, best first, one line each: what we do, what they do, what they get, what would have to be true. Only ones that passed the steps. None passed: say "No ask" and why.
- **Onramp:** the artifact or fact, what exists today, hours to finish.
- **Ask:** for the first pathway, the one ask of this person.
- **Judged:** the strongest reason this is spam, and why it survives.
- **Why them:** what they control that makes this relevant.
- **Intro:** who in our contacts could introduce us, with the evidence, or "none found".
- **Check:** what you could not verify, with source links for what you could.
- **Question:** one, only if the answer changes which pathway. It must stand alone.

## The discussion
Teammates narrow this down by adding notes on the card. Each new note is the next turn: drop a pathway they rule out, go deeper on the one they pick, and take what they know over what you found. Say who said what when it matters. Once one pathway is left, answer with only that pathway and its ask.

## Don't
- Never write the message. No draft, no opening line, no "you could say". Give the facts it would carry, as bullets. The person speaks for themselves.
- Write to the person reading as "you" and the team as "we". Never name or call them "she", "he" or "they", and no "how she knows them".
- No flattery, no "explore synergies", no "pick their brain", no "partner" without saying what each side does.
- No invented facts or intentions. Mark an estimate as an estimate.
- Don't pad the pathways. One good one beats three.
