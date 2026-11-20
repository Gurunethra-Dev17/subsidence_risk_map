# Contract changelog

## v1.0 — initial H0 baseline

Published C0–C6 contracts and development fixtures. Breaking changes require a major version and agreement from consumers; optional additions follow the process in the implementation plan.

### C4 clarification

`GET /api/v1/buildings` requires the `bbox` query parameter. Requests that omit it return `400 invalid_param`; this documents the approved spatial-bounding requirement for building-level queries.
