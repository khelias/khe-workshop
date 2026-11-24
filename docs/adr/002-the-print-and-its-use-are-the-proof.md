# ADR-002: The real print and its use are the proof, a photo is optional

- **Status:** Accepted (2026-11-24); point 1 extended to a part printed on several plates on 2026-11-24
- **Supersedes:** point 1 of [ADR-001](001-published-parts-carry-their-proof.md)
- **Related:** [estate ADR-043](https://github.com/khelias/khe-architecture/blob/main/decisions/043-household-parts-are-public-source-built-into-khe-sites.md)

## Context

ADR-001 published a part only with a photo of the real print and a recorded use.
Taking and vetting a photo of each part in use is the one step nobody wants to
do, and it held back the first part. A photo also needs its own care before it
goes public: metadata removed and the room behind the part looked at.

Each published part already carries its replay, built from the G-code the
printer really ran. That shows the print layer by layer, which a photo does not.

## Decision

1. **A part is published with its replay, the date it was printed and a recorded
   use.** `proof.printed` is the date (`YYYY-MM-DD`) and `proof.use` one sentence
   in Estonian and English on where and how the part is used. The page shows both
   under the part's story. A part printed on several plates has a replay of each
   plate, and the page plays them one after another as one print.
2. **A photo is optional.** When `proof.photo` is set, the file must exist in
   `published/` and the page shows it; without one, the page is complete.

## Alternatives considered

- **Keep the photo required.** It would keep the room empty.
- **A frame from the printer's camera.** It shows the part on the bed, not in
  use, and only when taken before the part is removed.

## Consequences

- A part can go live as soon as it has been printed, used and replayed.
- The claim that a part is in use rests on the recorded sentence, not a picture.
