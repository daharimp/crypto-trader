# ADR-004: Baseline strategies precede ML

- **Status:** Accepted
- **Decision:** Implement buy-and-hold and simple systematic strategies before ML; FreqAI only after non-ML baselines exist (RT-03).
- **Reason:** ML must demonstrate incremental value against simpler, more interpretable alternatives.
- **Consequence:** The first useful prototype will not depend on model training.

Source: `docs/spec/architecture.md` §14.
