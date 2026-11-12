"""LLM providers behind the `ModelProvider` protocol (agent_graph/deciders.py).

- `factory.py`: builds a provider from an agent config (the only place that reads API keys)
- `gemini.py`: the Gemini adapter (google-genai SDK, imported only when a Gemini run starts)
- `throttle.py`: process-wide requests-per-minute limit
- `errors.py`: typed provider failures
"""
