# Phase 2: Foundry Agent Service API (Stateful Pattern)

**Status**: Architecture blueprint (ready to implement)  
**Target**: ARM Windows compatible (REST API approach)  
**Timeline**: Estimated 2-3 hours for core implementation

---

## 📊 Phase 1 → Phase 2 Transition

### What Phase 1 Validated
- ✅ Foundry endpoint connectivity  
- ✅ Entra authentication (scope: `https://ai.azure.com`)
- ✅ Multi-turn conversation (manual history replay)
- ✅ Response parsing and error handling
- ✅ Safety gates work correctly (jailbreak filtered)

### What Phase 2 Implements
- **Proper Agent Service API** (stateful conversations/threads)
- **Agent lifecycle management** (get → thread → message → run)
- **Conversation persistence** (tracked on Foundry side, not client side)
- **Streaming support** (async response waiting)
- **Enterprise-grade patterns** (async/await, error recovery, observability)

---

## 🏗️ Core Architecture

```
External App (ARM Windows)
    ↓ (HTTP via httpx)
Foundry Agent Service REST API
    ↓
Agent runtime (stateful)
    - Conversation/thread storage
    - Message history
    - Tool execution
    - Response generation
```

### Key Differences from Phase 1

| Aspect | Phase 1 (Responses API) | Phase 2 (Agent Service API) |
|--------|------------------------|---------------------------|
| **State** | Stateless (client replays history) | Stateful (server manages thread) |
| **History** | Manual array replay | Automatic thread persistence |
| **Multi-turn** | Client-side context management | Server-side conversation management |
| **Tools** | Limited orchestration | Full tool ecosystem + execution |
| **Streaming** | Not supported | Supported (SSE) |

---

## 🔧 Implementation Plan

### Phase 2a: REST API Client (httpx-based)

**File**: `scripts/phase_2_agent_service_client.py`

Core pattern:
```python
from azure.identity import AzureCliCredential
import httpx

class FoundryAgentServiceClient:
    def __init__(self, project_endpoint: str, agent_id: str, timeout: int = 30):
        self.project_endpoint = project_endpoint
        self.agent_id = agent_id
        self.timeout = timeout
        self.credential = AzureCliCredential()
        self.thread_id: Optional[str] = None
    
    async def create_thread(self) -> str:
        """Create conversation thread (server-persisted)."""
        token = await self._get_token()
        url = f"{self.project_endpoint}/threads"
        response = await self._post(url, token, {"metadata": {}})
        self.thread_id = response["id"]
        return self.thread_id
    
    async def send_message(self, content: str) -> str:
        """Send message to thread."""
        token = await self._get_token()
        url = f"{self.project_endpoint}/threads/{self.thread_id}/messages"
        response = await self._post(url, token, {
            "role": "user",
            "content": content
        })
        return response["id"]
    
    async def run_agent(self) -> dict:
        """Run agent on thread, get response."""
        token = await self._get_token()
        url = f"{self.project_endpoint}/threads/{self.thread_id}/runs"
        run_response = await self._post(url, token, {"agent_id": self.agent_id})
        
        # Poll for completion (proper async pattern)
        run_id = run_response["id"]
        return await self._poll_run(run_id, token)
    
    async def _poll_run(self, run_id: str, token: str, max_wait: int = 300) -> dict:
        """Poll run status until completed or timeout."""
        import time
        start = time.time()
        url = f"{self.project_endpoint}/threads/{self.thread_id}/runs/{run_id}"
        
        while time.time() - start < max_wait:
            response = await self._get(url, token)
            if response["status"] == "completed":
                return response
            elif response["status"] == "failed":
                raise Exception(f"Run failed: {response.get('error')}")
            await asyncio.sleep(1)
        
        raise TimeoutError(f"Run {run_id} did not complete within {max_wait}s")
    
    async def _get_token(self) -> str:
        """Get Entra token for https://ai.azure.com scope."""
        loop = asyncio.get_event_loop()
        token = await loop.run_in_executor(
            None, 
            self.credential.get_token, 
            "https://ai.azure.com"
        )
        return token.token
    
    async def _post(self, url: str, token: str, data: dict) -> dict:
        """Make authenticated POST request."""
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(url, json=data, headers=headers)
            response.raise_for_status()
            return response.json()
    
    async def _get(self, url: str, token: str) -> dict:
        """Make authenticated GET request."""
        headers = {"Authorization": f"Bearer {token}"}
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.get(url, headers=headers)
            response.raise_for_status()
            return response.json()
```

### Phase 2b: Test Scenarios

**File**: `scripts/phase_2_agent_service_scenarios.py`

Test cases:
1. **Single-turn query** (weather, entity control)
2. **Multi-turn conversation** (3+ turns, thread persistence)
3. **Tool execution** (agent calls tools, validates outputs)
4. **Error recovery** (timeout, invalid request, retries)
5. **Streaming response** (if endpoint supports SSE)

### Phase 2c: HA Integration Adapter

**File**: `custom_components/azure_openai_sdk_conversation/llm/foundry_agent_service_client.py`

Wraps `FoundryAgentServiceClient` for Home Assistant:
- Converts HA conversation state to Foundry thread
- Manages thread lifecycle
- Stores thread ID in entity attributes
- Handles tool responses back to agent

---

## 🔑 REST API Endpoints (Phase 2)

### Create Thread (Conversation)
```http
POST /projects/{project_id}/threads
Authorization: Bearer {token}

Response:
{
  "id": "thread_xyz",
  "created_at": "2026-05-04T20:00:00Z",
  "metadata": {}
}
```

### Send Message
```http
POST /projects/{project_id}/threads/{thread_id}/messages
Authorization: Bearer {token}

{
  "role": "user",
  "content": "What's the weather?"
}
```

### Run Agent
```http
POST /projects/{project_id}/threads/{thread_id}/runs
Authorization: Bearer {token}

{
  "agent_id": "agent_xyz"
}

Response:
{
  "id": "run_xyz",
  "status": "in_progress",
  "thread_id": "thread_xyz"
}
```

### Get Run Status / Response
```http
GET /projects/{project_id}/threads/{thread_id}/runs/{run_id}
Authorization: Bearer {token}

Response (when completed):
{
  "id": "run_xyz",
  "status": "completed",
  "output": {
    "messages": [
      {
        "role": "assistant",
        "content": "The weather in Amsterdam is...",
        "created_at": "2026-05-04T20:00:05Z"
      }
    ]
  }
}
```

---

## ✅ Implementation Checklist

- [ ] Create `FoundryAgentServiceClient` class with:
  - [ ] `create_thread()` 
  - [ ] `send_message(content)`
  - [ ] `run_agent()` with polling
  - [ ] Proper error handling + retries
  - [ ] Entra token management

- [ ] Implement Phase 2 test scenarios:
  - [ ] Single-turn query
  - [ ] Multi-turn conversation (thread persistence)
  - [ ] Tool validation
  - [ ] Error recovery
  - [ ] Performance benchmarking

- [ ] Create HA integration adapter:
  - [ ] Thread lifecycle in config entry
  - [ ] Message formatting for agent
  - [ ] Response extraction and tool handling
  - [ ] Fallback behavior on errors

- [ ] Documentation:
  - [ ] REST API reference (mapping to SDK docs)
  - [ ] Architecture diagram
  - [ ] Troubleshooting guide
  - [ ] Performance expectations (latency, tokens, cost)

---

## 🚀 Success Criteria

- ✅ Agent Service API responds to REST calls on ARM Windows
- ✅ Thread creation and persistence verified
- ✅ Multi-turn conversation maintains state on server
- ✅ Async polling pattern doesn't timeout
- ✅ Tool calls visible in output (if agent has tools)
- ✅ Error recovery works (retry on transient failures)
- ✅ Latency benchmarks < 15s per request
- ✅ Token usage tracked correctly

---

## 📚 References

- [Microsoft Foundry Agent Service - Runtime Components](https://learn.microsoft.com/en-us/azure/foundry/agents/concepts/runtime-components)
- [Azure AI Foundry REST API](https://learn.microsoft.com/en-us/rest/api/aifoundry/)
- [Python Agent Framework Docs](https://learn.microsoft.com/en-us/python/api/overview/azure/ai-agents-readme?view=azure-python)
- [Architecture Patterns - Workshop](https://microsoft.github.io/build-your-first-agent-with-azure-ai-agent-service-workshop/architecture/)

---

## 📋 Next: Phase 2a Implementation

Ready to implement REST client. Recommend starting with:

1. **Basic connectivity test**: Create thread, send message, run agent
2. **Multi-turn validation**: Thread ID persists across requests
3. **Performance measurement**: Latency and token tracking
4. **Error scenarios**: Timeout, invalid request, retries

