# Conflict Resolution: ADR-001 & ADR-007

## Summary of Conflict

| Aspect | Agent A | Agent B |
|--------|---------|---------|
| **Database** | Keep PostgreSQL | Switch to MongoDB |
| **Architecture** | Stay monolith | Prepare for microservices |
| **Philosophy** | Optimize for present | Optimize for future |

## Resolution

### Database Decision: **PostgreSQL (Agent A wins)**

**Rationale:**
- ADR-001 was made with full context; JSONB support is sufficient for document needs
- MongoDB's "better horizontal scaling" is premature optimization for a <10 person team
- PostgreSQL provides ACID guarantees critical for most business applications
- Migration cost from PostgreSQL to MongoDB would be substantial with unclear benefit
- Agent B's argument conflates "document-centric data" with "needs MongoDB" - PostgreSQL JSONB handles this well

**Compromise:** If document query patterns become a bottleneck, revisit with concrete metrics.

### Architecture Decision: **Modular Monolith (Compromise)**

**Rationale:**
- Agent A is right that microservices overhead is premature for team size <10
- Agent B raises valid concern about migration cost if we must decompose later
- **Solution:** Adopt "modular monolith" pattern
  - Keep single deployment (monolith benefits)
  - Enforce module boundaries in code (future extraction ready)
  - Define clear APIs between modules

**Action Items:**
1. Document module boundaries in architecture diagram
2. Establish inter-module communication patterns (no direct DB access across modules)
3. Set trigger conditions for extraction: team size >15 OR module needs independent scaling

## Final Verdict

| ADR | Status | Action |
|-----|--------|--------|
| ADR-001 (PostgreSQL) | **Upheld** | No change |
| ADR-007 (Monolith) | **Amended** | Update to "Modular Monolith" |

The conflict stems from different time horizons. Agent A's present-focused pragmatism is correct for database choice. Agent B's future-awareness is valuable but better addressed through modular architecture than technology changes.

---
*Resolver - Conflict Resolution*
*Generated: 2026-03-23*
