---
title: Hybrid Apps
status: planned
---

# Build Hybrid Apps

One application that is an ordinary business application *and* uses a model: a support desk where
tickets, permissions, and audit trails are conventional code, and classification, retrieval, and
drafting are AI. The point of the path is the boundary between them.

**This path is not written yet.** Its lessons land in phases 3 and 5 of
[the plan](https://github.com/xyberos/xyberos2.0/blob/master/site/implementation.md), and the design
they are written to is fixed in advance: [the hybrid design](../../hybrid-design.md). The
[roadmap](../../roadmap.md) tracks progress.

## The rule the path teaches

**AI recommends; application code decides.** A model may classify a ticket, retrieve a passage, or
draft a reply. It never sends one, never changes a permission, and never bypasses a status transition.
Sending requires an approval transition, recorded with the principal and the exact body that was
approved.

That rule is not left to the prose: [the design](../../hybrid-design.md) names the four assertions the
integration test makes, including the one that matters most — a request payload that claims a different
tenant changes nothing.

## Why the design came first

This path consumes both of the others: the traditional path supplies its CRUD, templates, and verified
principal, and the AI path supplies classification, retrieval, tools, and workflows. Because all three
paths ship in one release, a decision deferred to lesson seven would be a release slip rather than a
deferred path — so the lifecycle, the permission matrix, and the approval boundary were fixed before
the first lesson was written.
