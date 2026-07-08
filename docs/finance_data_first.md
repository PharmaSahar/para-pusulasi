# Finance Data-First Architecture

Finance channels must be data-first; LLMs may not originate live numerical facts.

## Rule

- LLMs may not invent or estimate live market numbers.
- The pipeline must fetch and validate live data before writing any finance script.
- The LLM may only verbalize validated fact bundles that the pipeline supplies.
- Historical or example claims must be explicitly marked as historical or illustrative.
- If no validated live data exists, exact live numbers must be omitted.

## Operating Principle

The finance pipeline should treat live numbers as system-owned facts, not model-generated content.

Recommended flow:

1. Pipeline fetches live market data from trusted sources.
2. Pipeline validates the data and builds a fact bundle.
3. LLM receives only the validated bundle.
4. LLM writes explanatory copy using those verified facts.

If the data cannot be validated, the pipeline should fall back to a qualitative summary without exact live figures.

## Scope

This rule applies to all finance content generation paths, including scripts, narration, and any downstream text that could publish live market values.