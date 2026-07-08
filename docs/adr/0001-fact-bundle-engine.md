# ADR 0001: Fact Bundle Engine for Finance Content

## Context

Finance channels publish content where live numbers matter. Recent hotfixes added factual freshness checks and a finance data-first rule, but the architecture still needs a clear system-level contract. The core risk is allowing an LLM to originate live numerical claims such as exchange rates, prices, or rates. That creates stale, inconsistent, or unverified output.

## Decision

Finance content must be generated from validated fact bundles.

- The pipeline is the authority for live market data.
- LLMs may verbalize validated facts, but may not originate live numerical claims.
- Before generation, the pipeline must fetch data and pass it through a pre-LLM validator.
- After generation, a post-LLM validator must confirm the text stayed within the supplied fact bundle.

In this model, the Fact Bundle Engine becomes the system boundary between external market data and language generation.

## Consequences

- Live numbers become system-owned facts instead of model output.
- Finance scripts become more predictable and easier to audit.
- Validation failures can fail closed before publication.
- The LLM remains useful for narration, framing, and explanation, while the pipeline retains factual authority.

## Non-goals

- Building a general-purpose research or trading engine.
- Allowing the LLM to query live APIs directly.
- Replacing the existing content generation pipeline.
- Solving all factual domains outside finance.

## Future Implementation Notes

- Define a typed fact bundle schema with source, value, timestamp, and validation status.
- Support multiple trusted providers per fact type.
- Mark historical or illustrative claims explicitly so they do not trigger live validation rules.
- If validation fails or no trusted data exists, omit exact live numbers and generate qualitative copy only.
- Keep the pre-LLM validator and post-LLM validator separate so each failure mode is visible.