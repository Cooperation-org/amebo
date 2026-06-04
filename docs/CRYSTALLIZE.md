# Crystallizing input down to output

A core function of amebo is to gather a high volume of input from many sources, then synthesize and **crystallize** it down to the smallest output that still carries the meaning the receiver needs. The synthesis step matters more than any single channel.

## The funnel shape

Amebo is a funnel. Input comes in from many places:

- **The world** — spiders, scrapers, RSS, watch lists, scheduled checks, webhook senders, any external signal a claw is pointed at.
- **A person's own production** — messages, notes, ideas, decisions a person (e.g. Golda) feeds in. People who use amebo produce a lot of input.
- **Categorical context** — bindings from abra (or any configured context tool) that a claw reads at each tick. The claws may also write findings back into a context store.
- **Other claws** — output from one claw can be input to another.

The volume on the input side is large by design. The job is to absorb it without losing meaning, not to throttle the source.

## The crystallize step is the key engine function

When it is time to produce output, the most important work amebo does is **distill**. Not summarize in the bureaucratic sense, but crystallize: keep the signal, drop the rest, in the receiver's voice and at the receiver's bandwidth.

For a human receiver, the bandwidth is brutal:

- **One or two lines** is the practical maximum for a cold ping. Three lines is already too much for a stranger or someone who is not in a working relationship with amebo on this thread.
- **More is allowed inside a ready working relationship**: once the receiver has indicated they are paying attention right now and want detail (a thread is open, they are asking follow-ups), amebo can expand. The default is short.
- **Length is a function of relationship state, not of content importance.** Important content does not earn more lines; it earns more careful crystallizing into the same one or two.

For a non-human receiver (another claw, a context store, a structured downstream system), the format constraint is different. The crystallize step still happens. The output shape just isn't bound by human reading bandwidth.

## What this means for the architecture

The crystallize step is not a feature of any one channel adapter. It is a discrete engine inside amebo that:

1. Takes the input pile a claw has accumulated for one output occasion (a tick, a trigger, a question).
2. Picks a receiver (who, what relationship state).
3. Picks a channel (Slack DM, slack thread reply, email, voice transcription, structured POST to a context store, etc.).
4. Crystallizes the input pile down to the smallest meaningful representation for that receiver + channel combination.
5. Hands the crystallized output to the channel adapter for delivery.

The channel adapter knows how to format and send. The crystallize step knows what to say.

A claw without a strong crystallize step is a firehose. A claw with a strong crystallize step is a useful colleague. This is the difference amebo has to defend.

## How this interacts with context stores

Per [`context-store-contract.md`](https://github.com/Cooperation-org/abra/blob/docs/overview/context-store-contract.md) (abra repo), a claw reads from and writes to one or more opaque context stores at each tick. The reads feed the input pile. The writes are themselves outputs that get crystallized before being POSTed; a store entry should not be a raw dump of what the claw saw. It should be the crystallized observation the claw wants the next reader (human or claw) to encounter.

## Status

This doc is a working note, not a built feature. It captures the architectural commitment so that when crystallize-engine code lands, it has a clear bar to meet.
