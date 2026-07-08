# AI Project Charter - Para Pusulasi

## Project Vision
Para Pusulasi is an Autonomous Media Operating System.

Its long-term goal is to discover valuable opportunities from multiple
information sources, transform those opportunities into high-quality media
content, and publish diversified content across multiple channels with minimal
human intervention.

This project is not a simple YouTube automation tool.

It is an autonomous content research, planning, generation, and publishing
platform.

## Current Stage
Current release:

v0.1.0

Completed foundations:

- Passive research event store
- Append-only architecture
- Stable opportunity identifiers
- Research replay engine
- Collector contract
- Google Trends collector
- GitHub Trends collector
- Reddit collector
- Schema versioning
- Research regression CI
- Replay determinism
- Documentation
- Contribution workflow

Current development branch:

v0.2.0-planning

## Long-Term Architecture
The system is divided into independent layers.

### Research Layer
Purpose:

Collect raw observations.

Rules:

- Passive only
- Append-only
- Never score
- Never rank
- Never prioritize
- Never modify existing events

Collectors should only observe reality.

### Replay Layer
Purpose:

Replay historical observations.

Rules:

- Deterministic
- Stream processing
- Fail-open
- Read-only

Replay exists to enable future algorithms without recollecting data.

### Analysis Layer (Future)
Responsibilities:

- Deduplication
- Opportunity clustering
- Trend detection
- Ranking
- Confidence scoring

This layer must never modify research history.

### Media Layer
Responsibilities:

- Script generation
- Thumbnail generation
- Video generation
- Shorts generation

### Publishing Layer
Responsibilities:

- Scheduling
- Upload
- Monitoring
- Reporting

## Development Principles
Every implementation should follow these rules.

### Small commits
One logical feature per commit.

### Small pull requests
One logical change per PR.

### Test before commit
Every feature requires targeted regression tests.

### Passive-first
Never introduce production behavior while building research foundations.

## Architectural Rules
Avoid:

- Hidden state
- Global mutable state
- Tight coupling
- Implicit behavior

Prefer:

- Event sourcing
- Deterministic algorithms
- Explicit interfaces
- Small composable modules

## AI Assistant Rules
When implementing code:

Always prefer:

- minimal patches
- reversible changes
- isolated features
- deterministic behavior

Never:

- refactor unrelated code
- silently change production behavior
- introduce hidden dependencies
- change architecture without approval

## Current Priority
Current objective:

Build v0.2.0 safely.

Priority order:

1. Product value
2. Reliability
3. Testability
4. Maintainability
5. Performance

Never sacrifice maintainability for speed.

## Ultimate Goal
The final vision is an autonomous system capable of:

- discovering opportunities
- understanding trends
- producing diverse, high-quality media
- publishing across multiple brands
- continuously learning from historical observations
- while remaining deterministic, observable, and maintainable
