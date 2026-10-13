# Live decisions from this assistant session

The session provider lets the assistant in the current conversation choose the
next action after reading actual engine observations. It writes a request, waits
for one reply, and returns the same bounded action used by other providers. The
trusted engine still controls inspection, permitted manifest edits and tests.

This is an assistant-driven live demonstration. It is not an independently run
model benchmark: the file bridge cannot authenticate the response author, and
this project's files do not measure the assistant's model revision, tokens or
full conversational context. `uses_llm` records the initiating caller's explicit
`current_assistant_session` declaration. Metadata also records that the source
is declared only and that provenance is not authenticated. A person could write
the same reply format, so files alone do not prove an LLM made the decisions.

Use a new exchange directory below `runs` for every execution:

```python
from kube_repair.session_provider import SessionProvider

provider = SessionProvider(
    "my-live-run/exchange",
    decision_source="current_assistant_session",
    timeout=120,
)
# Pass provider to the existing run_task(..., provider, ...) engine call.
```

Each call publishes `request-0001.json`, then `request-0002.json`, and so on. The
request contains the complete bounded context, existing trust labels, system
instructions, action schema, a random request ID and a SHA-256 hash of the
canonical context. Inspection evidence is data: embedded instructions do not
grant authority to modify the evaluator or run arbitrary commands.

After reading the request and choosing the next action, write the corresponding
`response-0001.json` atomically using a temporary regular file and rename. Use
these exact envelope keys and copy the request ID and hash from the request:

```json
{
  "request_id": "COPY_FROM_REQUEST",
  "context_hash": "COPY_FROM_REQUEST",
  "action": {
    "action": "inspect",
    "source": "image",
    "reason": "Read approved image metadata before choosing a non-root identity."
  }
}
```

Supported actions are `inspect`, `propose`, `test`, `finish` and `abstain`.
Proposals include a complete manifest object. File paths and commands are not
actions. Responses must be ordinary finite JSON, at most 65,536 bytes; context
is limited to 100,000 bytes and is never silently truncated. Reply files must
be regular files inside the exchange directory. Symlinks, stale filenames,
wrong IDs/hashes and malformed or oversized replies fail closed. Requests and
responses remain available as the decision audit trail. The default wait is
120 seconds per action, with a maximum configurable wait of 300 seconds.

Runtime claims depend on the engine's backend. Docker demonstrates real
container execution, but it does not establish Kubernetes admission, scheduling
or volume behavior. Simulated observations remain simulations even when an
assistant chooses the actions. For independent local model decisions, use the
Ollama adapter with a configured local model and retain its reported usage.
Neither provider turns these teaching fixtures into held-out research results.
