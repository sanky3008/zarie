# Environment Variables Guide

This document lists all environment variables needed for the Donna bot.

## Required Variables

### Telegram Configuration
```bash
TELEGRAM_BOT_TOKEN=your_telegram_bot_token_here
```
Your Telegram bot token from @BotFather.

---

## LLM Provider API Keys

### Primary Provider: DeepSeek (Direct API)
```bash
DEEPSEEK_API_KEY=your_deepseek_api_key_here
```
Your DeepSeek API key for the primary LLM calls.

### Fallback Provider: Together AI
```bash
TOGETHERAI_API_KEY=your_together_ai_api_key_here
```
**🆕 NEWLY ADDED - Required for fallback functionality**

Your Together AI API key. This provides automatic failover when DeepSeek API is down.
- Sign up at: https://api.together.ai
- Usually comes with $25 free credits
- Only used when primary DeepSeek API fails

---

## Web Search API Keys

### Tavily Search
```bash
TAVILY_API_KEY=your_tavily_api_key_here
```
Used for web search functionality.

### Perplexity Search
```bash
PERPLEXITY_API_KEY=your_perplexity_api_key_here
```
Alternative/additional web search provider.

---

## Optional Configuration

### Database Path
```bash
DB_PATH=path/to/your/database.db
```
Optional. If not set, defaults to `chats.db` in the parent directory.

### Webhook Configuration (Production)
```bash
WEBHOOK_URL=https://your-domain.com
PORT=8443
```
Optional. Used for webhook mode in production instead of polling.

---

## Setting Up Environment Variables

### Local Development (.env file)
Create a `.env` file in the project root:

```bash
# Copy this template and fill in your values
TELEGRAM_BOT_TOKEN=
DEEPSEEK_API_KEY=
TOGETHERAI_API_KEY=
TAVILY_API_KEY=
PERPLEXITY_API_KEY=
```

### Production (Railway/Render/etc.)
Add each variable in your deployment platform's environment variables settings.

---

## Priority: Get Together AI Key First! 🚨

**To enable the new fallback functionality:**
1. Go to https://api.together.ai
2. Sign up (free $25 credits)
3. Get your API key
4. Add as `TOGETHERAI_API_KEY`
5. Restart your bot

Without this key, your bot will still work but won't have automatic failover when DeepSeek is down.

