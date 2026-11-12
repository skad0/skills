# From a phone to the map

*For: Product*

```mermaid
flowchart LR
  phone["User phone"]
  page["Report page"]
  map["Map page"]
  held["Not public"]
  phone -->|"1. photo and place"| page
  phone -.->|"via Telegram"| map
  page -->|"2. new report"| map
  page -.->|"not public"| held
```

| Failure |
| --- |
| Report page → Not public: not public |

**Goal.** A user sends a street photo and the map shows the report.

| User impact |
| --- |
| No account is needed. |
| Faces and plates are hidden first. |
| A photo not fit for public is not shown. |
