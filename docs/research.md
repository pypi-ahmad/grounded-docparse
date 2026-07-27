# Design basis

The pipeline borrows two useful product patterns from LlamaParse and LandingAI ADE: layout-first structural extraction and coordinate-backed visual auditability. This repository does not call or reproduce either product.

Its accuracy strategy is intentionally small:

- draft all page regions with a strong vision model;
- independently inspect low-confidence, complex, and critical-literal candidates against the source image;
- enrich every visual from high-resolution crops batched eight at a time, while keeping nonvisual ambiguity checks bounded;
- constrain model responses with typed Structured Outputs; and
- fail closed when text lacks valid coordinates or verification.

OpenAI requests omit application-supplied prompt-cache keys, options, and breakpoints for endpoint compatibility. Provider-managed caching may still occur independently. The app has no local result cache.

Automated tests use synthetic documents and fake providers. An opt-in live regression checks the source-derived PublicWaterMassMailing expectations, but the repository does not generalize that result into benchmark accuracy, production throughput, or cost claims.
