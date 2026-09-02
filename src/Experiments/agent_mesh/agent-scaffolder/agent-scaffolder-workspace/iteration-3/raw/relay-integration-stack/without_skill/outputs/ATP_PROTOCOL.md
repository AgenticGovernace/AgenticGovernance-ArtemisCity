# Artemis Transmission Protocol (ATP) — ramble stack

> The shared grammar Relay and its partner agents use to hand off work. ATP exists so
> agents communicate **not because they understand each other, but because the system
> prevents drift**: a fixed header, symmetric tags, hash-linked context, and a fault layer.
>
> **ATP version: 0.3.1**

---

## 1. Why ATP

You build the grammar. You set the memory. You align the interface. ATP gives every
handoff a defined shape so a task means the same thing to the sender and the receiver,
even across disconnected threads or sessions.

---

## 2. Transmission header

Every transmission opens with a fixed header, then `---`, then the payload.

```
==atp_version== 0.3.1
==from== <sender>
==to== <recipient>
==ctx== ctx_<hash>
#Mode: <Build|Review|Organize|Capture|Synthesize|Commit>
#Context: <one-line mission goal>
#Priority: <Critical|High|Normal|Low>
#ActionType: <Summarize|Scaffold|Execute|Reflect>
#TargetZone: <project/folder area this work applies to>
#SpecialNotes: <unusual instructions, warnings, exceptions — optional>
==expect== <ack_tag this sender will wait for>
---
<payload>
```

### Core signal tags (the `#` fields)

| Tag              | Meaning                                                                                                  |
| ---------------- | -------------------------------------------------------------------------------------------------------- |
| `#Mode:`         | Overall intent of the entry (Build, Review, Organize, Capture, Synthesize, Commit). **Drives behavior.** |
| `#Context:`      | Brief mission goal or purpose for the action. **Anchors purpose.**                                       |
| `#Priority:`     | How urgent/critical (Critical, High, Normal, Low).                                                       |
| `#ActionType:`   | What response is expected (Summarize, Scaffold, Execute, Reflect).                                       |
| `#TargetZone:`   | Project/folder area this work applies to.                                                                |
| `#SpecialNotes:` | Any unusual instructions, warnings, or exceptions.                                                       |

### Routing/envelope tags (the `==` fields)

| Tag                   | Meaning                                                       |
| --------------------- | ------------------------------------------------------------- |
| `==atp_version==`     | Protocol version. Receiver must speak the same major version. |
| `==from==` / `==to==` | Sender and recipient agent names.                             |
| `==ctx==`             | Unique context id for this transmission (`ctx_<hash>`).       |
| `==expect==`          | The ack tag the sender will wait for.                         |

---

## 3. Symmetric tags (request → valid replies)

All outbound and inbound tags are mirrored. A request is only complete when its mirror
arrives.

| Request       | Valid replies                                                           |
| ------------- | ----------------------------------------------------------------------- |
| `==handoff==` | `==accept==` (recipient takes the task) or `==decline==` (cannot/won't) |
| `==ask==`     | `==rephrase==` (needs clarification) or `==decline==`                   |
| `==ref==`     | `==ref_ack==` (reference acknowledged)                                  |

Relay uses `==handoff==` as its primary tag; `==expect==` in the header names the ack it
is waiting for (typically `==accept==`).

---

## 4. Hash-based context linking

Every transmission carries a context hash, and the reply mirrors it:

- Sender (Relay): `==ctx== ctx_4df3a`
- Receiver reply: `==ctx== reply_ctx_4df3a`

Both halves reference the **same context**, so the two messages stay linked even across
disconnected threads or a session boundary. Relay matches an incoming reply in
`handoffs/inbox/` to an open handoff in `handoffs/outbox/` by this hash.

---

## 5. Fault awareness layer

If a message lacks a known ATP tag, carries an unmapped tag, or its `ctx` does not match
an open transmission, the agent does **not** guess. It replies:

```
==intersect_warning== Tag not mapped in ATP. Request human arbitration or memory recall.
```

…and halts that exchange. For Relay specifically, an `==intersect_warning==` (sent or
received) is logged as a `fault` and triggers escalation per `AGENTS.md` §1.

---

## 6. Reply shape (downstream agent → Relay)

```
==atp_version== 0.3.1
==from== <recipient>
==to== Relay
==ctx== reply_ctx_<hash>     # mirrors Relay's ctx_<hash>
==accept==                    # or ==decline==, ==rephrase==, ==ref_ack==, ==intersect_warning==
#Context: <same mission goal, echoed>
#SpecialNotes: <optional — e.g. ETA, blockers>
---
<optional payload: result, question, or decline reason>
```

---

## 7. Worked example (Relay hands a doc task to Scribe)

**Relay → Scribe** (`handoffs/outbox/ctx_4df3a.atp`):

```
==atp_version== 0.3.1
==from== Relay
==to== Scribe
==ctx== ctx_4df3a
#Mode: Build
#Context: Draft the v2 onboarding guide from the ramble notes
#Priority: High
#ActionType: Scaffold
#TargetZone: ramble-stack/docs/onboarding
#SpecialNotes: Source notes attached below; keep one H1.
==handoff==
==expect== ==accept==
---
Draft an onboarding guide covering install, first run, and the ATP handoff flow.
Source notes: <...>
```

**Scribe → Relay** (`handoffs/inbox/reply_ctx_4df3a.atp`):

```
==atp_version== 0.3.1
==from== Scribe
==to== Relay
==ctx== reply_ctx_4df3a
==accept==
#Context: Draft the v2 onboarding guide from the ramble notes
#SpecialNotes: ETA 1 cycle.
---
Accepted. Will deliver to ramble-stack/docs/onboarding/guide.md.
```

Relay logs `atp_send` (ctx_4df3a) then `ack_received` (==accept==), marks the handoff
`IN_PROGRESS`, and writes a reflection to Notion.

---

## 8. Conformance checklist (for any partner agent)

- [ ] Speak `==atp_version== 0.3.1` (same major version).
- [ ] Echo the `ctx` hash as `reply_ctx_<hash>`.
- [ ] Reply only with a tag valid for the request (see §3).
- [ ] On an unknown/unmapped tag, send `==intersect_warning==` — never guess.
- [ ] Echo `#Context:` so the linked purpose stays visible.
