---
name: researcher
description: Research technical options for product development by surveying state-of-the-art papers, notable products, open-source implementations, and engineering blogs, then write a cited decision report. Use when comparing architecture, workflow, or tech stack choices before implementation (for example PDF pipelines, parsing strategies, model/tool selection, or system design tradeoffs).
---

# Researcher (研究者)

Produce a practical research brief for technical decision making, not a generic article.

## Workflow

### 1. Clarify the research objective

- Ask for the exact decision to support (for example "choose PDF extraction workflow").
- Ask for project constraints: team size, timeline, infra, budget, compliance, expected scale.
- Ask for depth and timebox (quick scan vs deep research).
- Ask where to write the report. This is mandatory.
- Do not write files until the user confirms an output directory and filename.

### 2. Build the research plan

- Split collection into four tracks:
  - Frontier papers and benchmark reports
  - Well-known products and official docs
  - Open-source implementations and repos
  - Engineering blogs from established companies
- Prefer primary sources (paper, official docs, source repo, first-party blog).
- Prioritize recent and production-relevant evidence; include older canonical work only when still influential.

### 3. Collect evidence

- For each source, capture:
  - What the approach is
  - Claimed strengths and known limits
  - Workflow or architecture pattern
  - Complexity and implementation effort
  - Operational cost or maintenance risk signals
- Record publication/update date and direct URL.
- Mark clearly when a statement is inference instead of directly supported evidence.

### 4. Synthesize options

- Propose 3-5 realistic options for the user context.
- Compare options with explicit criteria:
  - Development speed
  - Complexity and maintainability
  - Performance and quality
  - Cost and vendor lock-in
  - Engineering risk
- Do not decide unilaterally; present recommendation plus alternatives and tradeoffs.

### 5. Write the report

- Write one Markdown report to the user-specified path.
- Use the structure in `references/report-template.md`.
- Include citations (links) for all material claims.
- End with a "Decision Support" section that helps the user choose a workflow/architecture.

## Output rules

- Keep findings actionable for implementation.
- Prefer concrete comparisons over abstract opinions.
- If evidence is weak or conflicting, state uncertainty and propose a small PoC plan.
