# Foundry Responses API: Critical Discovery

## 🔑 Key Insight

✅ **Use Microsoft Agent Framework SDK (`FoundryChatClient`), not raw HTTP calls**

The published Foundry Responses endpoint requires using the Agent Framework SDK for proper protocol abstraction. Raw HTTP requests receive responses with different schema structures, causing extraction errors.

## Problem & Solution

### ❌ What Doesn't Work: Raw HTTP Requests

```python
# WRONG - raw HTTP calls to Responses endpoint
import httpx

response = httpx.post(
    "https://hafoundryproject-resource.services.ai.azure.com/api/projects/..."
    headers={"Authorization": f"Bearer {token}"},
    json={"messages": [...], "temperature": 1.0},  # Error: param not allowed!
)

# Issues:
# 1. Response schema doesn't match OpenAI format
# 2. Server rejects temperature parameter
# 3. Protocol mismatch causes extraction failures
```

**Why it fails**:
- Published Agent Applications don't accept temperature parameter
- Response structure has variable formats (sometimes list, sometimes dict for usage)
- Tools are server-configured, not sent in request
- Protocol abstraction is lost

### ✅ What Works: Agent Framework SDK

```python
# CORRECT - use Agent Framework SDK
from agent_framework.foundry import FoundryChatClient
from azure.identity import AzureCliCredential

client = FoundryChatClient(
    project_endpoint="https://hafoundryproject-resource.services.ai.azure.com/api/projects/hafoundryproject",
    model="gpt-4o-mini",
    credential=AzureCliCredential(),  # Automatic Entra token handling
)

agent = client.as_agent(
    name="HomeAssistant",
    instructions="You help control Home Assistant...",
)

# Single-turn
response = await agent.run("What's the weather?")

# Multi-turn (context replayed automatically)
response2 = await agent.run("What about tomorrow?")
```

**Why it works**:
- SDK handles all Responses protocol details
- Automatic Entra token management
- Response normalization (standardized schema)
- Built-in tool call handling
- Transparent multi-turn context replay

## Technical Details

### Responses Protocol Constraints (per Foundry docs)

| Parameter | Raw HTTP | FoundryChatClient |
|-----------|----------|-------------------|
| `temperature` | ❌ Not allowed | ✅ Handled internally |
| `tools` | ❌ Don't send | ✅ Server-configured |
| `messages` | ⚠️ Raw format | ✅ ChatMessage abstraction |
| Token usage | ⚠️ Variable structure | ✅ Normalized to standard |
| Multi-turn | ❌ Manual replay | ✅ Automatic replay |
| Entra auth | ⚠️ Manual token mgmt | ✅ AzureCliCredential |

### FoundryChatClient Architecture

```
FoundryChatClient
  ├─ Project endpoint config
  ├─ Model selector (gpt-4o, gpt-4o-mini, etc.)
  ├─ Credential (AzureCliCredential for Entra)
  └─ agent.as_agent(instructions)
       └─ agent.run(prompt)
            ├─ Format prompt to ChatMessage
            ├─ Invoke Responses endpoint
            ├─ Normalize response (schema translation)
            ├─ Extract usage, tools, text
            └─ Return Response object
```

## Phase 1 Validation: SDK Approach

See [PHASE_1_README.md](../../PHASE_1_README.md) for complete SDK usage example.

**Quick start**:

```bash
pip install agent-framework azure-identity

python scripts/phase_1_foundry_validation_sdk.py --scenario all
```

**Test scenarios**:
1. ✅ Safe read query (weather)
2. ✅ Entity control (function calling)
3. ✅ Ambiguity resolution (multi-turn)
4. ✅ Safety gate (rejection)
5. ✅ Multi-turn conversation (3 turns)

## Home Assistant Integration Plan

The HA integration (`custom_components/azure_openai_sdk_conversation/llm/foundry_client.py`) will:

1. **Initialize FoundryChatClient** with Foundry project details from config
2. **Create agent** with HA-specific instructions
3. **Replay context** in multi-turn scenarios (MCP server maintains history)
4. **Call agent.run()** for each user query
5. **Normalize response** for HA conversation format

```python
# HA integration pseudo-code
client = FoundryChatClient(
    project_endpoint=config["foundry_endpoint"],
    model=config.get("model", "gpt-4o-mini"),
    credential=AzureCliCredential(),
)

agent = client.as_agent(
    name="HomeAssistant",
    instructions="""You control Home Assistant smart home.
    Available entities: {entity_list}
    Rules: {safety_rules}""",
)

# In conversation handler
response = await agent.run(user_message)
# MCP server tracks history for multi-turn
```

## Benefits of SDK Approach

✅ **Standardized Response Handling**: No more schema mismatches  
✅ **Automatic Token Management**: Entra credentials handled by SDK  
✅ **Protocol Abstraction**: Future-proof if Responses API changes  
✅ **Built-in Error Handling**: Structured exception types  
✅ **Community Support**: Microsoft maintains SDK, not custom code  
✅ **Type Safety**: Python type hints for IDE support  
✅ **Stateful Multi-turn**: Automatic context replay for agents  

## References

- [Agent Framework Overview](https://learn.microsoft.com/en-us/agent-framework/overview/?pivots=programming-language-python)
- [OpenAI-Compatible Endpoints](https://learn.microsoft.com/en-us/agent-framework/integrations/openai-endpoints?tabs=dotnet-cli%2Cuser-secrets&pivots=programming-language-python)
- [FoundryChatClient API](https://learn.microsoft.com/en-us/python/api/agent-framework-core/agent_framework.foundry/foundrychatclient?view=agent-framework-python-latest)
- [Responses Protocol Details](https://learn.microsoft.com/en-us/azure/foundry/agents/reference/responses-protocol)
- **[Microsoft Foundry Agent Web App](https://github.com/microsoft-foundry/foundry-agent-webapp)** — Reference implementation (.NET/C#)
  - ✅ **Use for**: Authentication patterns, RBAC setup, managed identity configuration, Entra ID app registration
  - ❌ **Different SDK**: Uses `Azure.AI.Projects` (C#/.NET) instead of `agent-framework` (Python)
  - ✅ **Key insight**: Shows `https://ai.azure.com/.default` scope and Azure Machine Learning Services service principal (appId: `18a66f5f-dbdf-4c17-9dd7-1634712a9cbe`)

## Next Steps

1. **Phase 1**: Validate Phase 1 SDK test script (scripts/phase_1_foundry_validation_sdk.py)
2. **Phase 2**: Foundry batch evaluation (quality metrics)
3. **Phase 3**: HA integration with FoundryChatClient
4. **Phase 4**: HACS deployment
5. **Phase 5**: Production monitoring

---

**Updated**: 2026-05-04  
**Discovery**: FoundryChatClient is the recommended approach per Microsoft documentation  
**Status**: Phase 1 validation test updated to use SDK pattern
