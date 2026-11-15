# From a phone to the map

*For: Tech lead*

```mermaid
flowchart TB
  client["User"]
  service["Report server"]
  storage["Photo files"]
  map["Map page"]
  held["Not shown on the map"]
  client -->|"1. new report"| service
  service -->|"2. original, record, safe photo"| storage
  map -->|"3. request"| service
  service -->|"4. public reports"| map
  service -.->|"Report held for review"| held
  client -.->|"via Telegram"| service
```

| Failure |
| --- |
| Report held for review → Not shown on the map |

**Goal.** A user sends a street photo and the map shows the report.

| Tradeoffs and failure points |
| --- |
| Public only after a safe photo. |
| Originals stay private; two files and a worker. |
| Photo check is an outside service. |
