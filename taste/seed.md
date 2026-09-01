# Taste seed — Jamie fills this, not an agent

The curator reads this file (or `taste/seed.yaml`) as its day-1 gate.
An AI-written seed would train the curator on an invented taste and still
look like it was working. Until you write yours, the bundled stand-in at
`data/taste_seed.yaml` is used and labeled as such.

Preferred drop: `taste/seed.yaml` with this shape:

```yaml
keeps:
  - stars: 5
    question: >
      A specific question in your voice, with a named population and a mechanism.
    why: One line on why this is a keep.

kills:
  - stars: 1
    question: What are the implications of AI in healthcare?
    why: Seminar title. No population, no mechanism.
```
