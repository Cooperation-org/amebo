# Amebo preferences & behavior principles

> Golda's directional notes (2026-06-09), dictated from experience using Claude Code and
> Claude chat. These are **product/behavior preferences for Amebo**, not an architecture
> spec — design is being handled in a separate effort. Capture and absorb the intent;
> don't treat the wording as prescriptive of implementation.

## 1. Default to extreme concision

Agents talk far too much, and it's actively annoying. The core job of a chat agent is the opposite of generating volume: take a lot of information, decide which few words actually matter, and say only those — meaningful words backed by **verified links and real information**, not generated filler.

Because Amebo will run on cheaper models, this won't come for free. Likely needs either:
- strict instructions enforcing brevity, and/or
- a dedicated layer that condenses / synthesizes the underlying information before it reaches the human.

**Default mode = extremely concise.**

## 2. Clarify before building — never run ahead

Agents (and the people following them) keep racing off to build the *wrong* thing — team members lose days running ahead on work that wasn't what was needed. Amebo should carry not just skills but a high-level disposition that **clarifying and communicating is the most important thing**, more important than producing output.

The point isn't to hand-hold — people may not need much guidance — it's that the *bias* should be toward gaining clarity, not toward generating a pile of stuff. Default posture: short, clarifying conversation first; build once it's actually clear what to do.

**Never use multiple choice.** It's obnoxious and inhuman — you don't talk to a real person by handing them A/B/C/D. Ask like a human, in plain conversation. Never do the multiple-choice thing.

## 3. Lead with intent, and keep learning

Amebo's core job is to understand the *intent* of the person it's talking to, pull up the relevant context, and surface it only when needed. Assume the person is smart and has a real intent — listen and lean into that intent, and where useful help them sharpen it ("is this what you mean? is this how I can help?"). Otherwise stay out of the way. Concise throughout.

Self-improving understanding: when Amebo has to research to figure out what something means — especially a word or phrase the person clearly expected it to already know — once it lands on the right meaning, **record it in abra** so next time it just knows. Understanding compounds.

## 4. Loadable business-development skills

The harness has a way of loading skills (this isn't prescriptive about Claude's exact architecture). We want Amebo to load different *types* of business-development skills as needed — e.g. communicating, clarifying intent, sensing what kind of artifact would actually be welcome.

For a first round of communication, the welcome artifact is usually **very concise**: a brief diagram, a one-pager — not a long document. Humans don't want to read walls of text. BD is genuinely complex and iterative (clarify → small artifact → clarify → …).

## 5. The business-development flow

Rough stages Amebo should understand and support:

1. **Research the field** — what's happening in the space and who the key people are.
2. **Embed in their ecosystems** — follow those key people (LinkedIn or wherever they post); join where they gather (Discord, Signal, Slack) and participate genuinely as a member for a while, to actually understand what they're doing.
3. **Reach out only when appropriate** — offer something genuinely helpful (a service or a pilot). *Not* noisy, blasted outreach of our stuff. Understand first, then reach out in a way that fits their situation. Common paths: they have funding and a goal → they hire us for a project; or we partner with them to seek funding together when both sides need it.
4. **Outreach demonstrates understanding** — the initial contact already reflects their situation, framed in terms that make sense to them.
5. **The meeting** — we should have done the research *beforehand*. They should not have to explain themselves to us — coming in without that understanding has been a repeated mistake. Arrive already understanding them, already knowing which parts of our offering are relevant, and be concise. The meeting's purpose is to find a concrete next step: something someone will eventually pay for, a non-monetary partnership, or a directly proposed pilot.
6. **Deliver fast** — once there's a concrete thing, turnaround must be quick. Set the turnaround times in **both the task tracker (Taiga) and the CRM**.

**Amebo's highest-value BD job: watch the turnaround times and flag when they're slipping.** The first signal a prospect gets from us is whether we're fast, responsive, and say sensible (non-AI-slop) things. Fast matters enormously — but it must not be junky. Helping people hit those turnarounds (and guiding/assisting juniors who need it) is one of the first things Amebo should help with.

## 6. Model / key switching (technical)

Amebo needs to switch between **models and API keys**, for cost and for access reasons:
- Opus is expensive; reserve it for where it's worth it.
- Different keys for different purposes — e.g. an individual Claude Max account / Max API (which carries its own credits), plus whatever org keys we have.
- Be able to switch keys *and* switch models, including using cheaper ones (Plan, Minimax) — and **spin off subagents on the cheaper models** for work that doesn't need the top model.
- Soon we'll run a model on **our own hardware** — so self-hosted will be another target to route to.

**But don't switch mid-thread.** Conversation threads benefit from server-side (prompt) caching, so when there's a live conversation/thread going, prefer to keep it on the same model/key. Switch at natural boundaries, not mid-conversation.

## 7. Per-user, per-session credential management

We already have credential encapsulation (see `docs/CREDENTIAL_HELPER.md`) — build on it, don't reinvent.

- **Each user uses their own API key.** Team members enter their own keys for using the Claude Code SDK *through* Amebo; Amebo manages credentials per user.
- **Sometimes a team key applies instead** — especially for an open-source / self-hosted model we run.
- **Credential selection should be smart.** When a user wants some intelligence, Amebo decides *which* key to use (the user's own, a team key, the self-hosted model) rather than always asking.
- **Load at session start, extend as needed.** When a user starts a session they pick the credentials they need; the session's credential bundle can be added to during the session as new needs arise. Don't make the user decide constantly — **prompt only when actually needed**.
- **Shared-service credentials** (Taiga, CRM, etc.) some users will want to share — be careful how those are stored. (Believed already encapsulated; verify against the credential helper.)

**Sessions are first-class.** During a session Amebo holds that session's credential bundle **in memory, cached for that specific session**. This needs a strong, explicit concept of *sessions* in the architecture. Amebo is Python — concurrency via threading / event loop is fine — but the design should clearly support concurrent per-session bundles held in memory. (Hopefully the session model is already there; confirm.)
