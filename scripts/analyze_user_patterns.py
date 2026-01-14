#!/usr/bin/env python3
"""
Script to analyze how users are using Zarie - as Chief of Staff or Accountability Partner.
This script runs on production data via env variables.
"""

import os
import sys
import json
import csv
import asyncio
import litellm
from datetime import datetime
from zoneinfo import ZoneInfo
from dotenv import load_dotenv

# Add parent directory to path to import modules
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from agent.state.state import State
from agent.prompt import get_system_prompt

# Load environment variables
load_dotenv()

class UserPatternAnalyzer:
    def __init__(self):
        """Initialize analyzer with database connection."""
        self.state = State()
        self.results = []

    def get_all_users(self):
        """Get all unique user IDs from chats_context table."""
        env = os.getenv('ENV', 'LOCAL').upper()
        database_url = os.getenv('DATABASE_URL')

        if env == 'PROD' and database_url:
            print("Using PostgreSQL database...")
            try:
                import psycopg2
                conn = psycopg2.connect(database_url)
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT DISTINCT user_id, COUNT(*) as msg_count
                    FROM chats_context
                    GROUP BY user_id
                    HAVING COUNT(*) > 10
                    ORDER BY msg_count DESC
                """)
                rows = cursor.fetchall()
                conn.close()
                return [row[0] for row in rows]
            except Exception as e:
                print(f"Error connecting to PostgreSQL: {e}")
                return []
        else:
            print("Using SQLite database...")
            db_path = os.path.join(
                os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
                'chats.db'
            )
            if not os.path.exists(db_path):
                print(f"Database not found at {db_path}")
                return []

            import sqlite3
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()
            cursor.execute("""
                SELECT DISTINCT user_id, COUNT(*) as msg_count
                FROM chats_context
                GROUP BY user_id
                HAVING COUNT(*) > 10
                ORDER BY msg_count DESC
            """)
            rows = cursor.fetchall()
            conn.close()
            return [row[0] for row in rows]

    def build_user_context(self, user_id, user_timezone='Asia/Kolkata'):
        """Build context for a user similar to how Zarie builds it."""
        # Get user messages (exclude summarised)
        messages = self.state.get_messages(user_id, exclude_summarised=True)

        if not messages:
            return None

        # Build context similar to _prepare_messages in agent.py
        context_messages = []

        # Add system prompt (only takes user_id)
        system_prompt = get_system_prompt(user_id)
        context_messages.append({
            "role": "system",
            "content": system_prompt
        })

        # Add user messages (convert from dict format to LiteLLM format)
        for msg in messages:
            context_msg = {
                "role": msg["role"],
                "content": msg["content"]
            }

            # Add tool_calls if present
            if "tool_calls" in msg and msg["tool_calls"]:
                context_msg["tool_calls"] = msg["tool_calls"]

            # Add tool metadata for tool responses
            if "tool_call_id" in msg and msg["tool_call_id"]:
                context_msg["tool_call_id"] = msg["tool_call_id"]
            if "tool_name" in msg and msg["tool_name"]:
                context_msg["name"] = msg["tool_name"]

            context_messages.append(context_msg)

        return context_messages

    async def analyze_user_pattern(self, user_id, user_timezone='Asia/Kolkata'):
        """Analyze a single user's usage pattern."""
        print(f"\nAnalyzing user: {user_id}")

        # Build user context
        context_messages = self.build_user_context(user_id, user_timezone)

        if not context_messages:
            print(f"  No messages found for user {user_id}")
            return None

        # Create analysis query from Developer
        timestamp = datetime.now(ZoneInfo("UTC"))
        timestamp_local = timestamp.astimezone(ZoneInfo(user_timezone))

        day_name = timestamp_local.strftime("%A")
        day = timestamp_local.day
        month = timestamp_local.strftime("%b")
        year = timestamp_local.year

        if 10 <= day % 100 <= 20:
            suffix = "th"
        else:
            suffix = {1: "st", 2: "nd", 3: "rd"}.get(day % 10, "th")

        date_str = f"{day_name}, {day}{suffix} {month} {year}"
        time_str = timestamp_local.strftime("%H:%M")

        developer_message = {
            "role": "user",
            "content": f"""Date: {date_str}
Time: {time_str}
Timezone: {user_timezone}
FROM: Developer
Message: Based on the conversation history with this user, how are they primarily using Zarie? Please analyze and categorize their usage into one of these two patterns:

THE KEY QUESTION: Is Zarie DOING THE WORK, or REMINDING the user to do it?

1. Chief of Staff - Zarie ACTIVELY DOES WORK to save the user's time:
   - Researching information (search for X, find Y, compare options)
   - Getting real-time updates (news, stocks, sports scores, events)
   - Monitoring and alerting (track auction updates, alert on price changes)
   - Synthesizing information (daily news summary, weekly recap)
   - Searching and gathering data
   - Providing briefings and updates
   - Answering questions that require looking things up

   Key indicator: Zarie PERFORMS COGNITIVE WORK - researching, monitoring, synthesizing, searching
   Question to ask: "Did Zarie do work the user would otherwise have to do?"

2. Accountability Partner - Zarie PASSIVELY REMINDS and TRACKS to keep user on course:
   - ALL types of reminders (personal, professional, one-time, recurring)
   - Daily check-ins ("Did you workout today?")
   - Logging and tracking activities (exercise, tasks, habits)
   - Weekly/periodic progress reports and summaries
   - Birthday and relationship reminders
   - Medicine, bill payment, meeting reminders
   - ANY reminder to keep user accountable for doing something

   Key indicator: Zarie REMINDS, TRACKS, and CHECKS IN - the user still does the actual work
   Question to ask: "Is the user doing the work, with Zarie keeping them on track?"

IMPORTANT DISTINCTIONS:
- "Remind me to call mom" = Accountability Partner (Zarie reminds, user calls)
- "Find me the best flight to Delhi" = Chief of Staff (Zarie researches)
- "Remind me about the meeting at 3pm" = Accountability Partner (Zarie reminds, user attends)
- "What's happening in IPL auction?" = Chief of Staff (Zarie monitors and informs)
- "Did I workout this week?" = Accountability Partner (Zarie tracks user's activities)
- "Search for hotels in Goa under 5k" = Chief of Staff (Zarie does research)
- "Remind me to pay electricity bill" = Accountability Partner (Zarie reminds, user pays)
- "Give me daily tech news summary" = Chief of Staff (Zarie aggregates information)

Please provide your answer in this EXACT format:

PRIMARY_PATTERN: [Chief of Staff OR Accountability Partner]
CONFIDENCE: [High OR Medium OR Low]
PERCENTAGE: [X% for primary pattern]
KEY_EXAMPLES: [2-3 specific examples that clearly show the pattern]
REASONING: [1-2 sentences explaining why this pattern dominates]"""
        }

        # Add developer message to context
        analysis_messages = context_messages + [developer_message]

        try:
            # Call LiteLLM for analysis (NOT storing this in DB)
            response = await litellm.acompletion(
                model="gemini/gemini-2.5-flash",
                messages=analysis_messages,
                max_tokens=2048,
                temperature=0.3,
                timeout=30
            )

            analysis_result = response.choices[0].message.content

            result = {
                "user_id": user_id,
                "analysis": analysis_result,
                "message_count": len(context_messages) - 1,  # Exclude system prompt
                "timestamp": timestamp.isoformat()
            }

            print(f"  ✓ Analysis complete")
            return result

        except Exception as e:
            print(f"  ✗ Error analyzing user {user_id}: {e}")
            return {
                "user_id": user_id,
                "error": str(e),
                "message_count": len(context_messages) - 1,
                "timestamp": timestamp.isoformat()
            }

    async def analyze_all_users(self):
        """Analyze all users and generate report."""
        users = self.get_all_users()

        if not users:
            print("No users found to analyze.")
            return

        print(f"\nFound {len(users)} users to analyze")
        print("="*80)

        for user_id in users:
            result = await self.analyze_user_pattern(user_id)
            if result:
                self.results.append(result)

            # Small delay between users to avoid rate limits
            await asyncio.sleep(1)

        # Save results to file
        self.save_results()

    def save_results(self):
        """Save analysis results to CSV and JSON files and print summary."""
        if not self.results:
            print("\nNo results to save.")
            return

        # Create output directory if it doesn't exist
        output_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "analysis_output")
        os.makedirs(output_dir, exist_ok=True)

        # Generate filename with timestamp
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        json_file = os.path.join(output_dir, f"user_pattern_analysis_{timestamp}.json")
        csv_file = os.path.join(output_dir, f"user_pattern_analysis_{timestamp}.csv")

        # Save to JSON (full data)
        with open(json_file, 'w') as f:
            json.dump(self.results, f, indent=2)

        # Save to CSV (parsed and readable)
        with open(csv_file, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow([
                'User ID',
                'Message Count',
                'Primary Pattern',
                'Confidence',
                'Percentage',
                'Key Examples',
                'Reasoning',
                'Error'
            ])

            for result in self.results:
                if "error" in result:
                    writer.writerow([
                        result['user_id'],
                        result.get('message_count', 'N/A'),
                        'ERROR',
                        '',
                        '',
                        '',
                        '',
                        result['error']
                    ])
                else:
                    # Parse the structured response
                    analysis = result.get('analysis', '')

                    primary_pattern = ''
                    confidence = ''
                    percentage = ''
                    key_examples = ''
                    reasoning = ''

                    # Extract fields from structured response
                    for line in analysis.split('\n'):
                        line = line.strip()
                        if line.startswith('PRIMARY_PATTERN:'):
                            primary_pattern = line.replace('PRIMARY_PATTERN:', '').strip()
                        elif line.startswith('CONFIDENCE:'):
                            confidence = line.replace('CONFIDENCE:', '').strip()
                        elif line.startswith('PERCENTAGE:'):
                            percentage = line.replace('PERCENTAGE:', '').strip()
                        elif line.startswith('KEY_EXAMPLES:'):
                            key_examples = line.replace('KEY_EXAMPLES:', '').strip()
                        elif line.startswith('REASONING:'):
                            reasoning = line.replace('REASONING:', '').strip()

                    writer.writerow([
                        result['user_id'],
                        result.get('message_count', 'N/A'),
                        primary_pattern,
                        confidence,
                        percentage,
                        key_examples,
                        reasoning,
                        ''
                    ])

        print("\n" + "="*80)
        print(f"Analysis complete! Results saved to:")
        print(f"  CSV:  {csv_file}")
        print(f"  JSON: {json_file}")
        print("="*80)

        # Print summary
        print("\nSUMMARY:")
        print("-"*80)

        chief_of_staff = 0
        accountability_partner = 0
        errors = 0

        for result in self.results:
            if "error" in result:
                errors += 1
                continue

            analysis_text = result.get("analysis", "")

            # Parse the PRIMARY_PATTERN field
            if "PRIMARY_PATTERN:" in analysis_text:
                for line in analysis_text.split('\n'):
                    if line.strip().startswith('PRIMARY_PATTERN:'):
                        pattern = line.replace('PRIMARY_PATTERN:', '').strip().lower()
                        if 'chief of staff' in pattern:
                            chief_of_staff += 1
                        elif 'accountability' in pattern:
                            accountability_partner += 1
                        break
            else:
                # Fallback to old parsing if new format not found
                if "chief of staff" in analysis_text.lower():
                    chief_of_staff += 1
                else:
                    accountability_partner += 1

        print(f"\nTotal users analyzed: {len(self.results)}")
        print(f"Chief of Staff usage: {chief_of_staff}")
        print(f"Accountability Partner usage: {accountability_partner}")
        print(f"Errors: {errors}")
        print(f"\nPercentages:")
        total = chief_of_staff + accountability_partner
        if total > 0:
            print(f"  Chief of Staff: {chief_of_staff/total*100:.1f}%")
            print(f"  Accountability Partner: {accountability_partner/total*100:.1f}%")
        print("\n" + "="*80)

        # Print individual results (simplified)
        print("\nTOP 10 INDIVIDUAL RESULTS:")
        print("-"*80)
        for i, result in enumerate(self.results[:10], 1):
            print(f"\n{i}. User: {result['user_id']} | Messages: {result.get('message_count', 'N/A')}")

            if "error" in result:
                print(f"   ✗ Error: {result['error']}")
            else:
                analysis = result.get('analysis', '')
                # Extract just the key fields for console display
                for line in analysis.split('\n'):
                    line = line.strip()
                    if line.startswith('PRIMARY_PATTERN:') or line.startswith('CONFIDENCE:') or line.startswith('PERCENTAGE:'):
                        print(f"   {line}")

        if len(self.results) > 10:
            print(f"\n... and {len(self.results) - 10} more users")
        print(f"\nSee full results in CSV: {csv_file}")
        print("-"*80)

async def main():
    """Main entry point."""
    print("="*80)
    print("Zarie User Pattern Analyzer")
    print("Analyzing: Chief of Staff vs Accountability Partner Usage")
    print("="*80)

    analyzer = UserPatternAnalyzer()
    await analyzer.analyze_all_users()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n\nAnalysis interrupted by user.")
    except Exception as e:
        print(f"\n\nError: {e}")
        import traceback
        traceback.print_exc()
