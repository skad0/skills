# From a phone to the map

*For: Tech lead*

```mermaid
flowchart TB
  client["Client"]
  service["Service"]
  storage["Storage"]
  map["Map page"]
  held["Not public"]
  client -->|"1. new report"| service
  service -->|"2. original, record, safe photo"| storage
  map -->|"3. request"| service
  service -->|"4. public reports"| map
  service -.->|"not public"| held
  client -.->|"via Telegram"| service
```

**Goal.** A user sends a photo of a street problem, and the report is shown on a public map.

- Public only after a safe photo: failure means never shown, and not at once.
- Originals stay private; cost is two files and a worker.
- Photo check is an outside service; form, photo work, and map share one place.
