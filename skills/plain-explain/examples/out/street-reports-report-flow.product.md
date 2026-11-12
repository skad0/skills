# From a phone to the map

*For: Product*

```mermaid
flowchart LR
  phone["Phone"]
  page["Report page"]
  map["Map page"]
  held["Not public"]
  phone -->|"1. photo and place"| page
  phone -.->|"via Telegram"| map
  page -->|"2. new report"| map
  page -.->|"not public"| held
```

**Goal.** A user sends a photo of a street problem, and the report is shown on a public map.

- No account is needed.
- Not shown at once: faces and plates are made hard to read first.
- A photo not fit for public is not shown.
