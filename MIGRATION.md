# Migration Guide: From FoliniC Repository

This document provides step-by-step instructions for users migrating from the original [FoliniC/azure_openai_sdk_conversation](https://github.com/FoliniC/azure_openai_sdk_conversation) repository to this maintained fork with **Microsoft Foundry Agent support**.

## Why Migrate?

This fork adds:
- ✨ **Microsoft Foundry Agent Integration** (v1.5.0+) — Use Foundry Published Agents as your LLM backend
- 🔄 **LLM Backend Selector** — Choose between auto/azure/foundry backends
- 📈 **Continued Updates** — Active maintenance and new features
- 🆘 **Foundry Support** — Dedicated documentation and configuration guide

**Backward Compatible**: Existing Azure OpenAI configurations continue to work without changes.

## Migration Steps

### Step 1: Add New HACS Repository

1. Open **Home Assistant**
2. Navigate to **Settings** → **Devices & Services** → **HACS**
3. Click the **⋮ (menu)** button in the top-right corner
4. Select **Custom repositories**
5. Paste this repository URL: `https://github.com/JohanDeWeerdtMSFT/azure_openai_sdk_conversation`
6. Select **Category**: `Integration`
7. Click **Create**

### Step 2: Update the Integration

1. Go to **Home Assistant** → **Settings** → **Devices & Services**
2. Find your **Azure OpenAI SDK Conversation** integration instance
3. Click the **⋮ (menu)** button → **Check for updates**
4. If v1.5.0+ is available, click **Upgrade**
5. **Restart Home Assistant** when prompted

### Step 3 (Optional): Remove Old HACS Source

If the original FoliniC repository was added as a custom HACS source:

1. **Home Assistant** → **Settings** → **Devices & Services** → **HACS**
2. Click **⋮ (menu)** → **Custom repositories**
3. Find `https://github.com/FoliniC/azure_openai_sdk_conversation` (if listed)
4. Click the entry to expand, then click the **trash icon** to remove it

**Note**: Removing the old repository is optional but recommended to avoid confusion.

### Step 4: Verify Configuration

✅ **Your existing configuration is preserved!** No manual reconfiguration needed.

To verify everything works:

1. Open **Home Assistant**
2. Test your conversation — send a message to your agent
3. Check logs for any errors: **Settings** → **System** → **Logs**
4. Look for entries from `custom_components.azure_openai_sdk_conversation`

## Troubleshooting

### Integration Shows as "Unknown"

This is normal after updating. Restart Home Assistant:
1. **Settings** → **System** → **System Options**
2. Click **Restart Home Assistant**
3. Wait 2-3 minutes for the integration to reload

### HACS Shows "Upgrade Failed"

1. Clear your browser cache (Ctrl+Shift+Delete)
2. Refresh the HACS page
3. Try updating again
4. If still failing, restart Home Assistant and retry

### Configuration Errors

If you see errors in the logs:

1. **Settings** → **Devices & Services** → Find your integration instance
2. Click **Options** or **Configure**
3. Verify your Azure OpenAI API key and endpoint are correct
4. Check that "LLM Backend" is set to "azure" or "auto" (for backward compatibility)
5. **Save**

## Using Foundry (Optional)

Once migrated, you can optionally enable Microsoft Foundry:

1. **Settings** → **Devices & Services** → Find your integration instance
2. Click **Options**
3. Set **LLM Backend** to `Foundry` (or keep as `auto`)
4. Enter your **Foundry Endpoint** URL and **API Key** (from Azure Portal)
5. **Save** and test

See [README.md](README.md#using-microsoft-foundry-v150) for detailed Foundry setup instructions.

## Need Help?

- 📖 See [AGENTS.md](AGENTS.md) for detailed architecture and deployment guide
- 🐛 Open an issue on [GitHub](https://github.com/JohanDeWeerdtMSFT/azure_openai_sdk_conversation/issues)
- 💬 Check [Home Assistant Community Forums](https://community.home-assistant.io/)

## Attribution

- **Original Creator**: [FoliniC](https://github.com/FoliniC)
- **This Fork**: [JohanDeWeerdtMSFT](https://github.com/JohanDeWeerdtMSFT)
- **Foundry Integration**: Microsoft Foundry SDK & Responses API

---

**Last Updated**: 2026-05-04
