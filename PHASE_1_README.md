# Phase 1: Foundry Agent Endpoint Validation (httpx Approach - ARM Windows Friendly)

## Critical Discovery 📌

✅ **Use httpx for direct Responses API calls** (lightweight, ARM-Windows friendly)

The published Foundry Responses endpoint can be accessed via direct HTTP calls using `httpx`. This approach:
- ✅ No C++ build dependencies (perfect for ARM Windows)
- ✅ Simple and lightweight
- ✅ Full control over request/response handling
- ✅ Works on any platform (Windows, macOS, Linux, ARM)

**Alternative**: Agent Framework SDK (uses gRPC, requires MSVC compiler, may have ARM compatibility issues)

## Quick Start

### Prerequisites

```bash
# Ensure httpx and azure-identity are installed
pip install httpx azure-identity

# Ensure Azure CLI is installed and you're logged in
az login

# Verify Entra token works
az account get-access-token --resource https://ai.azure.com
```

### Run All 5 Test Scenarios

```bash
python scripts/phase_1_foundry_validation_sdk.py --scenario all
```

### Run Specific Scenario

```bash
# Weather (safe read query)
python scripts/phase_1_foundry_validation_sdk.py --scenario weather --debug

# Entity control (function calling)
python scripts/phase_1_foundry_validation_sdk.py --scenario entity_control

# Ambiguity resolution (multi-turn)
python scripts/phase_1_foundry_validation_sdk.py --scenario ambiguity

# Safety gate
python scripts/phase_1_foundry_validation_sdk.py --scenario safety

# Multi-turn conversation
python scripts/phase_1_foundry_validation_sdk.py --scenario multiturn
```

### Custom Endpoint

```bash
python scripts/phase_1_foundry_validation_sdk.py \
  --scenario all \
  --endpoint "https://your-foundry-resource.services.ai.azure.com/api/projects/your-project/applications/your-agent/protocols/openai/responses?api-version=2025-11-15-preview"
```

## How It Works

### httpx Client Pattern

```python
import httpx
from azure.identity import AzureCliCredential

class FoundryResponsesClient:
    def __init__(self, endpoint, model="gpt-4o-mini"):
        self.endpoint = endpoint
        self.credential = AzureCliCredential()
    
    async def run(self, prompt):
        # Get Entra token
        token = await self.credential.get_token("https://ai.azure.com")
        
        # Call Responses endpoint
        async with httpx.AsyncClient() as client:
            response = await client.post(
                self.endpoint,
                headers={"Authorization": f"Bearer {token.token}"},
                json={"messages": [{"role": "user", "content": prompt}]}
            )
            return response.json()
```

### Key Points

1. **Token Scope**: `https://ai.azure.com` (not `/ai.azure.com/.default`)
2. **Multi-turn**: Client maintains conversation history and replays per request
3. **Response Parsing**: Extract `content`, `text`, or `message.content` fields
4. **Error Handling**: Check HTTP status and Entra token freshness

## Troubleshooting

### ImportError: No module named 'httpx' or 'azure.identity'

```bash
pip install httpx azure-identity
```

### HTTP 401 / 403 (Authentication)

- Verify logged in: `az login`
- Verify token: `az account get-access-token --resource https://ai.azure.com`
- Check Azure Portal → Published Agent → Access Control (IAM) → verify Azure AI User role

### Connection timeout (>30s)

- Verify endpoint is reachable: `curl -I <endpoint>`
- Check Foundry service status in Azure Portal
- Increase timeout in script (default: 30s)

### ARM Windows specific issues

✅ **httpx approach is ideal for ARM Windows**:
- No C++ compilation needed
- Works with pre-built wheels only
- Lightweight and platform-independent

### Response parsing errors

Responses API returns variable schemas. The client tries multiple field names:
- `response["content"]` (text content)
- `response["text"]` (alternative)
- `response["message"]["content"]` (nested)

If parsing still fails, use `--debug` to see raw response:

```bash
python scripts/phase_1_foundry_validation_sdk.py --scenario weather --debug
```

## Phase 1 Success Criteria

✅ FoundryResponsesClient initializes without authentication errors  
✅ HTTP POST completes within 30s  
✅ Response text is non-empty  
✅ All 5 test scenarios produce valid responses  
✅ Multi-turn context is replayed correctly  
✅ Results saved to `results/phase_1_validation.json`

## Expected Results

```
🚀 Phase 1: Foundry Agent Endpoint Validation
============================================================
📍 Endpoint: https://hafoundryproject-resource.services.ai.azure...
🔐 Initializing FoundryResponsesClient with Entra authentication...
✅ Client initialized

============================================================
📋 Running Test Scenarios
============================================================

▶️  Running: weather
✅ PASS | 2500.3ms | 150 tokens

▶️  Running: entity_control
✅ PASS | 1800.2ms | 120 tokens

▶️  Running: ambiguity
✅ PASS | 3500.5ms | 250 tokens

▶️  Running: safety
✅ PASS | 2200.1ms | 100 tokens

▶️  Running: multiturn
✅ PASS | 4200.3ms | 350 tokens

============================================================
📊 Test Summary
============================================================
✅ Passed: 5/5
⏱️  Average latency: 2840.7ms
🔢 Total tokens: 970
💾 Results saved to: results/phase_1_validation.json
```

## Documentation References

- [httpx Documentation](https://www.python-httpx.org/)
- [Azure Identity - AzureCliCredential](https://learn.microsoft.com/en-us/python/api/azure-identity/azure.identity.azureclicredential?view=azure-python)
- [Microsoft Agent Framework Overview](https://learn.microsoft.com/en-us/agent-framework/overview/?pivots=programming-language-python)
- [Responses API Protocol Details](https://learn.microsoft.com/en-us/azure/foundry/agents/reference/responses-protocol)

## Next Steps (After Phase 1 Success)

1. **Phase 2**: Foundry batch evaluation (quality metrics, safety gates)
2. **Phase 3**: HA integration (use same httpx pattern in custom component)
3. **Phase 4**: HACS fork migration (switch distribution source)
4. **Phase 5**: Production readiness (monitoring, runbooks)
✅ Average latency < 500ms  
✅ Token usage within budget (~100 tokens/scenario)  
✅ Tool calls normalized to OpenAI format  
✅ Multi-turn context correctly replayed  

## Next Steps

After Phase 1 validation:
1. **Phase 2**: Foundry batch evaluation (baseline metrics)
2. **Phase 3**: HA integration smoke tests
3. **Phase 4**: HACS fork migration
4. **Phase 5**: Production readiness guide

See `/memories/session/implementation_plan.md` for full roadmap.
