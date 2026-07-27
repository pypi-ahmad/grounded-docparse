# Architecture

```text
upload -> Luna draft -> manager page plan -> selected Luna specialists
                                      \-> bounded Terra repair when justified
       -> deterministic validation -> Markdown + agentic JSON + annotated PDF
       -> schema proposal -> Luna extraction -> evidence validation
                                      \-> one Terra critic repair when needed
```

Streamlit runs the workflow synchronously in one local process. There is no API server, queue, worker, database, application cache, cost estimator, or artifact store.

Within that process, the parser schedules strict 20-page windows and uses up to 10 isolated page threads. Each page owns its gateway, usage, and trace state. Worker progress is replayed on the caller thread; page results are sorted before cross-page hierarchy and final exports are built.

`ingest.py` validates and renders inputs. `gateways.py` owns strict OpenAI calls, usage accounting, and the agent trace. `pipeline.py` bounds manager delegation to two specialists per round and two repair rounds, assigns stable IDs, validates boxes and ordering, and builds the hierarchy. `extraction.py` validates editable schemas and requires evidence for every non-null scalar. `render.py` emits Markdown, agentic JSON v2, legacy JSON, and the annotated PDF.

Terra is not a mandatory second pass. The manager may request it only for a risky target during parse repair; extraction gets at most one Terra critic repair after deterministic validation fails. This limits cost and latency at the tradeoff of not pursuing open-ended autonomous recovery.
