# Documentation

Start here:

| Document | What it covers |
|---|---|
| [OVERVIEW.md](OVERVIEW.md) | What the system is, the tech stack, the architecture, current state, and the path to production |
| [RATIONALE.md](RATIONALE.md) | Why it is built this way, what was deliberately left out, and what production would cost |

Reference material:

| Document | What it covers |
|---|---|
| [ARCHITECTURE.md](ARCHITECTURE.md) | Module-level detail, request lifecycle, state model, known limitations |
| [DECISIONS.md](DECISIONS.md) | The formal decision record, 12 ADRs with trade-offs and evidence |
| [DATA-MODEL.md](DATA-MODEL.md) | Column semantics, the three kinds of empty cell, the graph schema |
| [API.md](API.md) | Endpoint reference: parameters, responses, error cases |
| [MAINTENANCE.md](MAINTENANCE.md) | Running, testing, extending, debugging, and the invariants not to break |

## Reading order

If you are reviewing this project, read [OVERVIEW.md](OVERVIEW.md) then
[RATIONALE.md](RATIONALE.md). Between them they cover what was built and why,
and they are written to be read rather than referred to.

If you are picking up the code, go on to [ARCHITECTURE.md](ARCHITECTURE.md) and
[MAINTENANCE.md](MAINTENANCE.md).

If you want the reasoning behind one specific choice in its formal form,
[DECISIONS.md](DECISIONS.md) has it as a numbered record.

## The short version

The data is never cleaned automatically. Detection and editing are separate
modules with deliberately different powers, because a wrong read is visible and a
wrong write is not.

The knowledge graph is built directly from the columns rather than extracted by a
language model, because the data is already structured and extraction would add
error where there is none. The retrieval-and-grounded-generation part of GraphRAG
is kept; community detection and global search are not, and that boundary is
stated rather than blurred.

Edits run through four fixed operations, never generated code, and every one is
scoped, versioned, audited and reversible. The original upload cannot be edited
away.
