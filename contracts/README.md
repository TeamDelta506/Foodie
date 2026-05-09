# Contracts

This directory is the team's source of truth for how server, client, and database talk to each other.

In Week 5 it's empty. In Week 6, your team's coordinator runs an LLM session using the About page as input, and produces:

- `CONTRACTS.md` — the API contract: which endpoints exist, what they accept, what they return, what errors are possible
- Role-specific guides — what each team member is building this week, with file boundaries clearly drawn

These contracts are **load-bearing**, not advisory. The server-side dev builds against the contract. The client-side dev consumes against the same contract. The db-security dev validates the schema matches. When the contract is wrong, you fix the contract first, then the code.

Don't put implementation here. This is where decisions about *what* the system does live, separate from the *how*.
