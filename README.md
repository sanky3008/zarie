# Zarie

An AI accountability partner that helps you stay on top of your commitments, habits, and goals — without judgment.

Zarie lives in Telegram and Slack. You tell it what you want to stay accountable to, and it checks in with you, sends reminders, and celebrates your wins.

**[Read the technical deep dive: How Zarie Works Under the Hood](https://sankalpphadnis.com/writing/how-zarie-works.html)**

## How it works

Zarie uses a dual-agent architecture:

- **Main agent** — handles real-time conversations with users over Telegram and Slack
- **Worker agents** — autonomous background agents that manage scheduled reminders and recurring tasks

A scheduler runs every 60 seconds, finds due events, invokes the relevant worker agent to process the reminder, and routes the response back to the user.

```
User message → Telegram/Slack bot → MessageBuffer (debounce) → Main agent → LLM + tools → Response

Scheduler (60s) → Due events → Worker agent → Main agent → Send message to user
```

## Features

- **Reminders & recurring tasks** — set one-time or recurring reminders using natural language
- **Accountability check-ins** — Zarie proactively follows up on things you've committed to
- **Web search** — ask Zarie to look things up via Brave search
- **Google Calendar integration** — connect your calendar to view and create events
- **Multi-platform** — works on Telegram and Slack with shared conversation context
- **Timezone-aware** — all scheduling respects the user's local timezone

## Tech stack

- **Python** with async throughout
- **LiteLLM** for LLM routing
- **python-telegram-bot** and **slack_bolt** for messaging
- **SQLite** (local) / **PostgreSQL** (production) for conversation history and scheduling
- **MCP (Model Context Protocol)** for tool integration
- **Google OAuth** for Calendar access
- **Railway** for production hosting

## Setup

### Prerequisites

- Python 3.8+
- A Telegram bot token (from [BotFather](https://t.me/botfather))
- A Slack app with OAuth credentials
- An OpenAI API key (or compatible LLM provider via LiteLLM)
- PostgreSQL (production) or SQLite (local)

### Installation

```bash
git clone https://github.com/your-org/zarie.git
cd zarie

python -m venv venv
source venv/bin/activate

pip install -r requirements.txt
```

### Environment variables

Create a `.env` file:

```bash
# LLM
OPENAI_API_KEY=sk-...
LITELLM_DEBUG=false

# Telegram
TELEGRAM_BOT_TOKEN=...
BLOCKED_TELEGRAM_IDS=          # optional, comma-separated

# Slack
SLACK_CLIENT_ID=...
SLACK_CLIENT_SECRET=...
SLACK_SIGNING_SECRET=...

# Google OAuth (optional, for Calendar integration)
GOOGLE_CLIENT_ID=...
GOOGLE_CLIENT_SECRET=...
GOOGLE_REDIRECT_URI=http://localhost:8080/google/callback

# Database
DATABASE_URL=postgresql://user:pass@host:port/dbname   # production only
ENV=LOCAL                                               # LOCAL or PROD

# Web search (optional)
BRAVE_MCP_SERVER_URL=http://localhost:3000

# Deployment (optional, for Telegram webhook mode)
WEBHOOK_URL=https://your-domain.com
PORT=8443
```

### Running locally

```bash
# Interactive terminal chat (no Telegram/Slack needed)
python terminal_chat.py

# Run the Telegram + Slack bots
python main.py

# Run the scheduler (separate process, needed for reminders)
python run_scheduler.py
```

### Running in production (Railway)

1. Deploy `main.py` as the primary service
2. Deploy `run_scheduler.py` as a separate cron service (60-second interval)
3. Add a PostgreSQL addon and set `DATABASE_URL`
4. Set `ENV=PROD`

## Project structure

```
agent/                  Main Zarie agent (conversation, tool routing)
worker_agent/           Autonomous worker agents (reminders, scheduling)
event_manager/          Time-based event scheduling and triggering
slack_app/              Slack bot and OAuth installation store
telegram_bot.py         Telegram bot
run_scheduler.py        Cron scheduler for time events
main.py                 Entry point
user_manager.py         User database management
google_oauth_handler.py Google OAuth flow
terminal_chat.py        CLI chat for local testing
tests/                  Test suite
evals/                  Multi-turn conversation evaluations (DeepEval)
scripts/                Database migration and maintenance scripts
```

## Testing

```bash
pytest tests/

# Run conversation evaluations
pip install -r evals/requirements.txt
pytest evals/run_evals.py
```

## License

MIT
