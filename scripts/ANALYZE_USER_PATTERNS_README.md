# User Pattern Analysis Script

## Overview
This script analyzes how users are using Zarie by examining their conversation history and categorizing their usage into two primary patterns:

1. **Chief of Staff** - Task management, reminders, information tracking
2. **Accountability Partner** - Habit tracking, check-ins, progress reports

## How It Works

1. **Fetches all users** from the `chats_context` table (users with >10 messages)
2. **Builds context** for each user using the same method as Zarie:
   - Retrieves all non-summarized messages
   - Uses the same system prompt
   - Preserves conversation structure
3. **Sends analysis query** from "Developer" asking the AI to categorize usage
4. **Processes response** using LiteLLM (gemini-2.5-flash)
5. **Saves results** to JSON file without storing in database

## Important Notes

- ✅ **Does NOT store** analysis messages in `chats_context` table
- ✅ Uses helper functions from the codebase (not `invoke`)
- ✅ Respects environment variables for database connection
- ✅ Works with both SQLite (local) and PostgreSQL (production)

## Usage

### Local Development (SQLite)
```bash
cd /Users/sankalpphadnis/Documents/Donna/zarie
python scripts/analyze_user_patterns.py
```

### Production (PostgreSQL)
```bash
cd /Users/sankalpphadnis/Documents/Donna/zarie
ENV=PROD DATABASE_URL="postgresql://..." python scripts/analyze_user_patterns.py
```

Or with .env file:
```bash
# Ensure .env has:
# ENV=PROD
# DATABASE_URL=postgresql://...
python scripts/analyze_user_patterns.py
```

## Output

The script generates:

1. **Console output** with:
   - Progress for each user
   - Summary statistics
   - Preview of individual analyses

2. **JSON file** at `analysis_output/user_pattern_analysis_YYYYMMDD_HHMMSS.json` containing:
   - User ID
   - Full analysis text
   - Message count
   - Timestamp
   - Any errors encountered

### Example Output Structure
```json
[
  {
    "user_id": "123456789",
    "analysis": "Primary usage pattern: Chief of Staff\nConfidence level: High\n...",
    "message_count": 156,
    "timestamp": "2026-01-14T10:30:00Z"
  },
  {
    "user_id": "987654321",
    "analysis": "Primary usage pattern: Accountability Partner\nConfidence level: Medium\n...",
    "message_count": 89,
    "timestamp": "2026-01-14T10:31:05Z"
  }
]
```

## Dependencies

- Python 3.10+
- litellm
- python-dotenv
- psycopg2 (for PostgreSQL)
- All Zarie project dependencies

## Filtering

The script filters users by:
- Minimum 10 messages (to have enough data for analysis)
- Sorted by message count (most active users first)

To adjust the minimum message threshold, edit line 43 in the script:
```python
HAVING COUNT(*) > 10  # Change this number
```

## Rate Limiting

The script includes:
- 1 second delay between user analyses
- 30 second timeout per LiteLLM call
- Error handling for individual user failures

## Troubleshooting

### No users found
- Check database connection
- Verify users have >10 messages
- Check .env file configuration

### LiteLLM errors
- Verify OPENAI_API_KEY or relevant API key in environment
- Check model availability (gemini/gemini-2.5-flash)
- Review timeout settings

### Database connection errors
- For PostgreSQL: Verify DATABASE_URL format
- For SQLite: Check chats.db file exists
- Ensure ENV variable is set correctly

## Privacy & Data Safety

This script:
- ✅ Only reads from database (no writes except output file)
- ✅ Does NOT modify user conversation history
- ✅ Does NOT send developer messages to users
- ✅ Saves results locally for review
- ⚠️ Contains full conversation context in output file - handle securely

## Customization

### Change analysis prompt
Edit the `developer_message` in `analyze_user_pattern()` method (around line 183)

### Change output format
Modify `save_results()` method to change JSON structure or add CSV/other formats

### Change model
Modify line 216:
```python
model="gemini/gemini-2.5-flash"  # Change to different model
```

### Adjust analysis parameters
Lines 217-219:
```python
max_tokens=2048,     # Increase for longer analyses
temperature=0.3,     # Increase for more creative, decrease for more deterministic
```
