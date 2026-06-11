# Marketing & Communications Capability

**Status: captured, not scheduled.** Direction only — nobody is building this now.

Drip-with-templates is one optional element of a broader marketing/comms skill
(also: one-off/broadcast sends, content drafting). A team can switch on drip or never use it.

## Direction

**A drip is a claw** (BOUNDARIES, "one engine, two triggers": schedule fires → think →
send → log; a reply hands back into the live loop). It lives in **Amebo, not an Odoo
module**, so it can also sequence non-Odoo audiences (abra-only people, web-sourced
prospects). Reach beyond the CRM is the point.

Amebo owns only transient state (enrollment, step pointer, next-due, pending queue).
Everything durable is referenced, not duplicated:
- Contacts → Odoo; comms history → Odoo chatter (crystallize each send back); identity → abra.
- Suppression/unsubscribe → Odoo `mail.blacklist`/LinkedTrust; checked before every send.
- For Odoo-contact campaigns, **drive Odoo `mass_mailing`** (free Email Marketing) as the
  send/tracking/unsubscribe substrate instead of re-implementing it; send directly only for
  non-Odoo audiences. Background sends use the team identity `amebo:<team>`.

## First milestone is deliverability, not the architecture

The sequencing logic is the easy part. The real, blocking work:
- A dedicated **marketing sending subdomain** with its own SPF/DKIM/DMARC + warm-up — never
  the domain that sends transactional/OIDC/CRM mail.
- Compliance: `List-Unsubscribe`, physical address, honored opt-out.
- Reply detection → auto-pause the enrollment.

_Considered an Odoo `crm_drip` plugin (gets Odoo's designer/tracking/compliance for free) but
rejected: it can only reach Odoo contacts. Revisit only if drip becomes Odoo-contacts-only._
