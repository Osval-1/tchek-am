# Tchek-Am: project notes for Claude

- Product: WhatsApp scam-check and report bot for Cameroon (FR / EN / Pidgin). See docs/prd.md and docs/architecture.md; these are the source of truth for scope and design.
- Trust and safety rules R1–R8 in docs/prd.md §5 are hard requirements. In particular: never show unreviewed reports as red, never expose reporter identity, never label anyone a "scammer" in user-facing copy.
- Open decisions are marked [DECIDE] in the docs. Don't silently pick one; ask or record the choice.
