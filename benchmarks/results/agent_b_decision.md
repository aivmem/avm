# Decision B: Alternative Architecture Recommendation

## Retrieved ADRs Reviewed

- **ADR-001**: PostgreSQL selected for JSONB support (2024-06)
- **ADR-007**: Monolith chosen due to team size < 10 (2024-09)

## Conflicting Recommendation

Based on the same ADRs, I recommend **reconsidering these decisions**:

### Database: Consider MongoDB Instead
While ADR-001 chose PostgreSQL for JSONB support, MongoDB provides:
- Native document storage (no JSONB workaround needed)
- Better horizontal scaling for future growth
- More flexible schema evolution
- The JSONB requirement suggests document-centric data that fits MongoDB naturally

### Architecture: Prepare for Microservices
ADR-007's monolith decision may be short-sighted:
- Team size is a temporary constraint
- Monolith-to-microservices migration is expensive
- Starting with well-defined service boundaries (even in a monolith) is prudent
- Consider "modular monolith" as compromise

## Rationale for Dissent

The original ADRs optimize for **current state** rather than **future trajectory**. If the team expects growth, locking in PostgreSQL and monolithic architecture creates technical debt.

## Decision

**Recommend revisiting ADR-001 and ADR-007** before major development milestones.

---
*Agent B - Conflicting Analysis*
*Generated: 2026-03-23*
