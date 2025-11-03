# Together AI Fallback Setup Guide

## ✅ What Was Changed

Your bot now has **automatic failover** to Together AI's DeepSeek v3 model if your primary DeepSeek API fails!

### Files Updated:
- ✅ `agent/agent.py` - Added fallback for main agent
- ✅ `worker_agent/agent/agent.py` - Added fallback for worker agent
- ✅ `.env.example` - Documented required environment variable

---

## 🚀 How to Complete Setup

### Step 1: Get Your Together AI API Key

1. Go to **https://api.together.ai**
2. Sign up for a free account (usually comes with **$25 free credits**)
3. Navigate to **Settings → API Keys**
4. Create a new API key and copy it

### Step 2: Add the API Key to Your Environment

Add this line to your `.env` file:

```bash
TOGETHERAI_API_KEY=your_together_ai_api_key_here
```

**For Railway/Production:**
- Go to your Railway project settings
- Add a new environment variable: `TOGETHERAI_API_KEY`
- Set the value to your Together AI API key
- Redeploy if needed

### Step 3: Verify It's Working

The fallback is **automatic** - no code changes needed!

When your primary DeepSeek API fails (503 errors), the bot will:
1. ✅ Automatically retry the request 2 times
2. ✅ If still failing, switch to Together AI's DeepSeek v3
3. ✅ Continue serving users without interruption

---

## 🔧 How It Works

### Before (Old Code):
```python
response = litellm.completion(
    model="deepseek/deepseek-chat",
    messages=messages,
    tools=self.tools,
    tool_choice="auto"
)
```

### After (New Code):
```python
response = litellm.completion(
    model="deepseek/deepseek-chat",  # Primary
    messages=messages,
    tools=self.tools,
    tool_choice="auto",
    fallbacks=["together_ai/deepseek-ai/DeepSeek-V3"],  # 🔄 Automatic fallback
    timeout=30,  # 30 second timeout
    num_retries=2  # Retry primary 2 times before fallback
)
```

---

## 📊 Error Handling Flow

```
User sends message
        ↓
Try DeepSeek API (primary)
        ↓
    Failed? → Retry (attempt 1)
        ↓
    Failed? → Retry (attempt 2)
        ↓
    Failed? → Switch to Together AI
        ↓
    Success! → Respond to user
```

---

## 💰 Cost Considerations

### DeepSeek (Primary):
- **Your current provider**
- Usually cheaper, but less reliable

### Together AI (Fallback):
- **$25 free credits** on signup
- Only used when primary fails
- Pricing after free credits (check their website for latest):
  - Input: ~$0.14-0.28 per 1M tokens
  - Output: ~$0.28-0.56 per 1M tokens

**Important:** Fallback only triggers on failures, so most requests still use your primary (cheaper) DeepSeek API!

---

## 🧪 Testing the Fallback (Optional)

To test if the fallback works, you can temporarily:

1. Set an invalid `DEEPSEEK_API_KEY` in your `.env`
2. Send a test message to your bot
3. It should automatically use Together AI
4. Check logs for: `"Fallback to together_ai/deepseek-ai/DeepSeek-V3"`
5. Restore your real `DEEPSEEK_API_KEY`

---

## 🎯 What This Solves

### Your Original Error:
```
httpx.HTTPStatusError: Server error '503 Service Unavailable'
DeepseekException - "Service is too busy. We advise users to 
temporarily switch to alternative LLM API service providers."
```

### Now:
✅ When DeepSeek's API is overloaded (503 errors)
✅ When DeepSeek has network issues
✅ When DeepSeek has timeouts
✅ Bot automatically switches to Together AI
✅ Users don't see error messages
✅ **Zero downtime for your users!**

---

## 📝 Environment Variables Summary

You should have these in your `.env` file:

```bash
# Primary LLM (your current setup)
DEEPSEEK_API_KEY=sk-xxxxx

# Fallback LLM (newly added)
TOGETHERAI_API_KEY=xxxxx

# Telegram
TELEGRAM_BOT_TOKEN=xxxxx

# Other keys...
TAVILY_API_KEY=xxxxx
PERPLEXITY_API_KEY=xxxxx
```

---

## ❓ FAQ

**Q: Will this increase my costs?**
A: No! Fallback only triggers when primary fails. Plus, Together AI gives $25 free credits.

**Q: What if both providers fail?**
A: The error will be caught by your existing error handling in `main.py` and users will see a friendly error message.

**Q: Can I add more fallbacks?**
A: Yes! You can add multiple fallbacks:
```python
fallbacks=["together_ai/deepseek-ai/DeepSeek-V3", "gpt-4o-mini", "groq/llama-3.1-70b"]
```

**Q: How do I know when fallback is being used?**
A: Check your logs - LiteLLM will log when it switches to a fallback provider.

**Q: Is DeepSeek v3 on Together AI as good as direct API?**
A: Yes! It's the same model, just hosted on different infrastructure (often more reliable).

---

## ✅ Next Steps

1. Get your Together AI API key from https://api.together.ai
2. Add `TOGETHERAI_API_KEY` to your `.env` file
3. Restart your bot
4. That's it! Your bot is now fault-tolerant 🎉

---

## 🆘 Troubleshooting

### "Fallback not working"
- Check that `TOGETHERAI_API_KEY` is set correctly
- Verify the API key is valid (test at together.ai)
- Check logs for specific error messages

### "Still getting 503 errors"
- This means both providers are down (very rare)
- Consider adding more fallbacks (OpenAI, Groq, etc.)

### "Higher costs than expected"
- Check if primary is actually failing often
- Monitor usage at together.ai dashboard
- Consider fixing primary DeepSeek connection issues

---

**Questions?** Check the logs or create an issue!

