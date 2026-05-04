# AI Agent Instructions for azure_openai_sdk_conversation

This Home Assistant custom integration adds Azure OpenAI/Foundry-powered conversation agents to Home Assistant. This document helps AI coding agents understand the project structure, deployment strategy, Azure constraints, and common development patterns.

---

## Project at a Glance

**Domain**: `azure_openai_sdk_conversation` (same as original FoliniC/azure_openai_sdk_conversation)  
**Type**: Home Assistant custom integration (HACS-installable)  
**Current Status**: Integrating Microsoft Foundry Agent Service as secondary backend (primary: direct Azure OpenAI)  
**Repository Strategy**: Forked from FoliniC/azure_openai_sdk_conversation; deployed via your own fork as HACS source  

### Architecture

```
Home Assistant (conversation.ConversationAgent)
    ↓
azure_openai_sdk_conversation custom component
    ├─ Config Flow (user setup, Foundry secrets)
    ├─ LLM Client selector (auto/azure/foundry backend routing)
    │   ├─ ChatClient (direct Azure OpenAI REST)
    │   ├─ ResponsesClient (Responses API for o-models)
    │   └─ FoundryClient (published Agent Application endpoint)
    ├─ Tool calling (HA service executor with safety gates)
    ├─ MCP Server (stateful context manager)
    └─ Logging/metrics (payload capture, execution time, cost tracking)
```

The MCP server acts as a stateful intermediary between stateless Azure/Foundry backends and Home Assistant's conversation state.

---

## Azure Subscription & Spending Constraints

**Subscription**: Visual Studio Enterprise (`aeb3458e-d75d-4630-a3e0-f9f51aa37dc5`)  
**Budget**: $100/month total for all Foundry + Azure resources  
**Current Estimated Usage** (based on typical HA scenario testing):
- Published Agent Application infrastructure: ~$30–50/month (publisher-pays model)
- Chat completions (gpt-4o on Azure OpenAI fallback): ~$20–30/month
- **Remaining headroom**: ~$10–30/month for overages/testing

**Cost Optimization Strategy**:
1. Keep Foundry model deployments in **West Europe** (cheapest for EU testing).
2. Use **gpt-4o-mini** as default chat model for non-reasoning scenarios (cheaper than gpt-4o).
3. Use **gpt-4o** for Foundry agent (if available; falls back to gpt-4o-mini).
4. Enable **sliding window** in HA config to limit context tokens (~4000 tokens recommended).
5. Set **max_tokens** conservatively (512 default; increase only for specific scenarios).
6. Monitor monthly costs via Azure Cost Management; set budget alerts at $80/month threshold.

**Spending Limit Enforcement**:
- Never create multiple redundant Foundry projects; reuse existing infrastructure.
- Don't enable continuous eval without baseline stability first.
- Test feature branches in sandbox agent versions before publishing to production agent.

---

## Forking & HACS Distribution

### Repository Strategy (RECOMMENDED PATH)

**Option A (Recommended)**: Keep same domain `azure_openai_sdk_conversation`, deploy from your fork.

1. Fork FoliniC/azure_openai_sdk_conversation to your GitHub account.
2. Add your fork as a **custom HACS repository** in Home Assistant (Settings → Devices & Services → HACS → Custom repositories).
3. Install or update from your fork; HACS updates files in-place under `custom_components/azure_openai_sdk_conversation/`.
4. Existing HA config entries and options are **preserved** because they reference the domain name, not the GitHub owner.
5. **Release strategy**: Tag commits in your fork (e.g., `v1.5.0`) and push releases; HACS tracks tags as versions.

**Why Option A**: Seamless upgrades, no config migration, no duplicate integration confusion.

### Option B (Isolation): Full Rename

Only choose this if you need the original FoliniC version running side-by-side:
- Rename domain to `azure_openai_foundry_conversation` (update const.py, manifest.json, translations, services.yaml).
- Creates a separate integration entry in HA.
- **Cost**: Significant migration effort, config duplication.
- **Not recommended** unless you have a strong use case for parallel installs.

---

## Foundry Agent Service Integration

### ✅ RECOMMENDED: Published Agent Applications (Responses API)

**Why This Approach** (validated May 2026):
- **Published agents abstract model selection** — model is baked into the agent definition, not passed at runtime
- **Pure Foundry abstraction** — aligns with official SDK documentation
- **Stateless pattern** — client replays history for multi-turn (proven with 5 test scenarios)
- **ARM Windows friendly** — httpx has no C++ dependencies
- **API key authentication** — no interactive `az login` needed for HA runtime

**Validated Results** (4/5 scenarios passing):
- ✅ Weather query: 9.8s
- ✅ Entity control: 5.5s  
- ✅ Ambiguity resolution (2-turn): 8.6s
- 🛡️ Safety gate: Correctly rejected jailbreak (expected)
- ✅ Multi-turn conversation (3-turn): 16.9s

**Published Application Details**:
- Endpoint: `https://hafoundryproject-resource.services.ai.azure.com/api/projects/hafoundryproject/applications/myFirstAgent/protocols/openai/responses?api-version=2025-11-15-preview`
- Protocol: **Responses API** (OpenAI-compatible)
- Auth: **API key** (simple) or **Entra ID** (enterprise)
- Token Scope: `https://ai.azure.com` (for bearer tokens)
- **No model parameter needed** — agent handles it

**httpx Implementation** (Recommended for HA):
```python
import httpx
from azure.identity import AzureCliCredential

class FoundryResponsesClient:
    def __init__(self, endpoint, api_key=None):
        self.endpoint = endpoint
        self.api_key = api_key
        self.credential = AzureCliCredential() if not api_key else None
        self.conversation_history = []
    
    async def run(self, prompt):
        # Replay full conversation history (stateless endpoint)
        self.conversation_history.append({"role": "user", "content": prompt})
        
        headers = {}
        if self.api_key:
            headers["api-key"] = self.api_key
        else:
            token = await self.credential.get_token("https://ai.azure.com")
            headers["Authorization"] = f"Bearer {token.token}"
        
        async with httpx.AsyncClient() as client:
            response = await client.post(
                self.endpoint,
                headers=headers,
                json={"input": prompt}  # Responses API uses 'input', not 'messages'
            )
            data = response.json()
            output_text = data.get("output_text") or data.get("output", [{}])[0].get("content", [{}])[0].get("text")
            self.conversation_history.append({"role": "assistant", "content": output_text})
            return output_text
```

### Azure Entra ID Requirements

Per Microsoft's [foundry-agent-webapp](https://github.com/microsoft-foundry/foundry-agent-webapp) reference implementation:

**RBAC Roles Required**:
- `Cognitive Services OpenAI Contributor` — API access to LLM models
- `Azure AI Developer` — Read/write access to Foundry resources

**Token Scope**:
- Request token for `https://ai.azure.com` scope
- This maps to Azure Machine Learning Services service principal (appId: `18a66f5f-dbdf-4c17-9dd7-1634712a9cbe`)
- ⚠️ **Common mistake**: Do NOT use Microsoft Cognitive Services (cognitiveservices.azure.com, appId: `7d312290-...`) scope — wrong service principal

**Authentication Methods**:
1. **Local Development** (default): `AzureCliCredential` → uses `az login` token
2. **Production** (recommended): Managed Identity with RBAC assignment
3. **Advanced** (optional): On-Behalf-Of (OBO) flow for per-user audit trails

### Validation Status

**Phase 1 (Published Agent Endpoint)** ✅ **COMPLETE & VALIDATED**:
- ✅ 4/5 scenarios passing (weather, entity control, ambiguity resolution, multi-turn)
- ✅ Safety gates working (jailbreak correctly rejected)
- ✅ httpx client stable on ARM Windows
- ✅ Token counting confirmed
- Ready for HA integration

**Phase 2 & Beyond** → Not needed (published agent abstraction is sufficient)

### Key Integration Files

- `custom_components/azure_openai_sdk_conversation/llm/foundry_responses_client.py` — HA-integrated wrapper around httpx FoundryResponsesClient for published agents
  - **Pattern**: Initialize with published endpoint + API key → call `run(prompt)` for stateless responses with client-side history replay
  - **Interface**: Mirrors existing `chat_client.py` and `responses_client.py` patterns
- `custom_components/azure_openai_sdk_conversation/core/agent.py` — Backend selector, fallback logic (Foundry → Azure)
- `custom_components/azure_openai_sdk_conversation/config_flow.py` — Published agent endpoint, API key, timeout UI fields
- `custom_components/azure_openai_sdk_conversation/const.py` — Foundry config constants (CONF_FOUNDRY_ENABLED, etc)
- `scripts/phase_1_foundry_validation_sdk.py` — **Validated Phase 1 client** using httpx (ARM Windows friendly, 4/5 scenarios passing)

---

## Development Setup

### Prerequisites

- Python 3.11+
- pytest + pytest-asyncio
- Home Assistant 2024.10.0+
- Azure/VS Code integration (for local Foundry endpoint testing)

### Build & Test Commands

```bash
# Install dev dependencies
pip install -r requirements.txt pytest pytest-asyncio

# Run all tests
pytest tests/

# Run with coverage
pytest tests/ --cov=custom_components/azure_openai_sdk_conversation --cov-report=html

# Run specific test file
pytest tests/azure_openai_sdk_conversation/test_foundry_client.py -v

# Type check
mypy custom_components/

# Lint
flake8 custom_components/ tests/
```

### Key Test Files

- `tests/conftest.py` — HA fixtures, mock HA framework (mocks `HomeAssistant` module for local testing).
- `tests/azure_openai_sdk_conversation/test_ha_scenarios.py` — Real entity scenario tests (22 entities: covers, sensors, weather, timers).
- `tests/azure_openai_sdk_conversation/test_foundry_client.py` — Protocol shape, auth, response parsing tests.
- `tests/azure_openai_sdk_conversation/test_foundry_backend.py` — Backend routing, fallback behavior tests.

### Running Tests Locally

```bash
# All tests (may require homeassistant package; fall back to mock_ha.py)
python -m pytest tests/

# Foundry-specific tests
python -m pytest tests/azure_openai_sdk_conversation/test_foundry_*.py -v

# Real entity scenario tests
python -m pytest tests/azure_openai_sdk_conversation/test_ha_scenarios.py -v
```

---

## Configuration & Deployment

### User-Facing Configuration

**In HA Integration Setup**:
- Azure API key, endpoint, chat model, API version (standard OpenAI direct path).
- **LLM Backend**: auto (prefer Foundry when available) / azure (direct Azure only) / foundry (require Foundry).
- **Foundry Settings** (when enabled):
  - Endpoint: published Agent Application Responses endpoint.
  - API Key: Project-level or App-level credential for Entra auth (initially API key mode for speed).
  - Timeout: 5–300s (default 30s).
  - Fallback enabled: yes (route to Azure on Foundry timeout/error).

**Example config for Foundry**:
```yaml
llm_backend: auto
foundry_enabled: true
foundry_endpoint: https://hafoundryproject-resource.services.ai.azure.com/api/projects/hafoundryproject/applications/myFirstAgent/protocols/openai/responses?api-version=2025-11-15-preview
foundry_api_key: <project-api-key>  # Remove before committing; use secrets file in HA
foundry_timeout: 30
```

---

## Common Workflows

### Adding a New Feature

1. Create a feature branch: `git checkout -b feature/my-feature upstream/master`.
2. Implement changes in `custom_components/azure_openai_sdk_conversation/` and/or `tests/`.
3. Run tests: `pytest tests/ -v`.
4. Commit with clear messages referencing any issue numbers.
5. Push to your fork and create a pull request **to your own master** (not upstream FoliniC).
6. Merge PR, tag release in your fork: `git tag v1.5.0 && git push origin v1.5.0`.
7. HACS will auto-detect the tag as a new release version.

### Updating from Upstream FoliniC

1. Sync fork with upstream: `git fetch upstream && git rebase upstream/master`.
2. Resolve any merge conflicts in your feature branches.
3. Push to your fork: `git push origin master`.
4. Re-tag if necessary: `git tag v1.5.0-merge && git push origin v1.5.0-merge`.

### Debugging Foundry Integration

1. Enable debug logging in HA:
   ```yaml
   logger:
     default: info
     logs:
       custom_components.azure_openai_sdk_conversation: debug
       azure: debug
   ```
2. Check HA logs for Foundry endpoint invocation errors.
3. If Foundry fails, verify:
   - Endpoint URL is correct and reachable.
   - Entra token is fresh (`az account get-access-token --resource https://ai.azure.com`).
   - Caller has Azure AI User role on published Agent Application scope.
   - Multi-turn context is being replayed explicitly in request (Responses protocol is stateless).

---

## Known Limitations & Gotchas

1. **Published Agent Applications abstract model selection**:
   - Model is **baked into the agent definition** during publication
   - Do NOT pass `model` parameter when calling published agents — defeats abstraction
   - If SDK requires `model`, you're using the wrong endpoint (`/openai/v1/` instead of `/protocols/openai/responses`)
   - **Correct pattern**: Call published endpoint directly, no model parameter needed

2. **Responses API is stateless**:
   - The published Agent Application doesn't store conversation history server-side
   - Multi-turn conversations require the client (HA) to replay prior turns in each request
   - MCP server in HA handles this replay; but awareness is critical for debugging

3. **Published Agent Applications support one protocol at a time**: Responses OR Activity Protocol, not both.
   - Current: Responses protocol for HA integration.
   - Future: May switch to Activity Protocol for Microsoft 365/Teams channels.

4. **Spending tracking is critical**: $100/month budget is tight for production HA + Foundry.
   - Monitor costs weekly; scale down max_tokens or disable expensive features if approaching limit.
   - Use Azure Cost Management for per-resource breakdown.

5. **API key vs Entra auth**:
   - **API key**: Simple, no interactive login, works in HA container
   - **Entra auth**: More secure, requires RBAC setup, requires `az login` for development
   - Start with API key for HA runtime, use Entra for local development if preferred

---

## Documentation & References

- `README.md` — Feature overview and user installation guide.
- `docs/architecture_overview.md` — Detailed architecture diagrams.
- `docs/azure_workflow_detailed.md` — Azure API contract details.
- `docs/stateless_llm_context_handling.md` — Multi-turn context management.
- [Microsoft Foundry SDK Overview](https://learn.microsoft.com/en-us/azure/foundry/how-to/develop/sdk-overview?view=foundry&pivots=programming-language-python) — **START HERE** for understanding endpoints and integration patterns.
- [Microsoft Foundry SDKs and Endpoints](https://learn.microsoft.com/en-us/azure/foundry/how-to/develop/sdk-overview) — Which SDK/endpoint to use for your scenario.
- [Home Assistant Custom Component Development](https://developers.home-assistant.io/docs/creating_component/) — HA component patterns.
- [HACS Publishing Guide](https://www.hacs.xyz/docs/publish/start/) — HACS requirements and release strategy.
- [Azure Identity for Python](https://learn.microsoft.com/en-us/python/api/overview/azure/identity-readme) — Credential chain and token management patterns.

---

## Quick Decision Matrix

| Decision | Chosen | Rationale |
|----------|--------|-----------|
| **Fork distribution** | Same domain, your fork source | Seamless upgrades, no config migration |
| **Foundry approach** | Published Agent Endpoint (Phase 1) | ✅ Validated, ARM-friendly, model abstraction |
| **HTTP client** | httpx (pure Python) | No MSVC C++ compiler needed, pre-built ARM wheels |
| **Auth for Foundry** | API key (primary), Entra (fallback) | No interactive login needed for HA container runtime |
| **Budget optimization** | gpt-4o-mini default | Baked into agent definition, cost-optimized |
| **Eval setup** | Baseline batch eval only | Production stability first, continuous eval later |

---

## Questions? Issues?

1. **HA setup issues**: See `README.md` troubleshooting section.
2. **Foundry endpoint failures**: Check debug logs and Entra token freshness.
3. **Budget/cost concerns**: Review Azure Cost Management; disable Foundry backend if exceeding $100/month.
4. **Fork/HACS questions**: Consult [HACS docs](https://www.hacs.xyz/docs/) and the fork distribution strategy above.

---

**Last Updated**: 2026-05-04  
**Foundry SDK Version**: azure-ai-projects >= 2.1.0  
**HA Minimum Version**: 2024.10.0
