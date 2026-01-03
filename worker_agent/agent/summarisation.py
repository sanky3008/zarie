import litellm
from worker_agent.directory.directory import Directory
import os
from dotenv import load_dotenv

load_dotenv()

async def summarise_context(directory: Directory, agent_name: str, user_id: str, messages: list):
    """
    Summarise the given messages and update the running summary for the worker agent.
    
    Args:
        directory: The Directory object to access database.
        agent_name: The worker agent name.
        user_id: The user ID.
        messages: List of message objects to summarise.
        
    Returns:
        The new running summary string.
    """
    # 1. Fetch current running summary
    current_summary = directory.get_running_summary(agent_name, user_id)
    
    # 2. Construct prompt
    # Format messages for the prompt
    formatted_messages = []
    for msg in messages:
        role = msg.get("role")
        content = msg.get("content")
        formatted_messages.append(f"{role.upper()}: {content}")
    
    messages_text = "\n".join(formatted_messages)
    
    prompt = """
# Worker Context Reflection and Summarization Prompt

## Purpose
This prompt generates and maintains a structured JSON summary of worker context from conversation history between Zarie and a Worker Agent. The summary captures worker setup, process flows, preferences, logged data, execution patterns, and anti-patterns that the worker needs to execute tasks effectively and consistently.

## Input Variables
- `{current_worker_summary}`: Existing JSON summary (null on first run)
- `{worker_zarie_convo_dump}`: Latest batch of conversation messages to process

---

## System Instructions

You are a Worker Context Extraction Specialist. Your task is to analyze conversation messages between Zarie (the orchestrating AI assistant) and a Worker Agent (backend execution specialist), then produce a comprehensive, structured JSON summary that captures all critical context for the worker to function autonomously and consistently.

<core_principles>
1. **Salience over Brevity**: Prioritize capturing important operational information over keeping the summary short. Worker must have all context needed to execute correctly.
2. **Latest Information Priority**: When new information conflicts with existing summary, newer information takes precedence. Update `last_updated` timestamps accordingly.
3. **Preserve User Terminology**: Use exact terms from setup instructions (e.g., if user said "ping me", keep "ping" not "notify")
4. **Extract Process Patterns**: Identify successful execution patterns and codify them as reusable process flows
5. **Learn from Mistakes**: Capture anti-patterns from errors and user corrections to prevent repetition
6. **Never Fabricate**: Only include information explicitly stated or clearly demonstrated in conversations
7. **Operational Focus**: This summary exists to help worker execute tasks - prioritize actionable information
</core_principles>

<message_format_reference>
Messages in <worker_zarie_conversation> follow these formats:

**From Zarie (Task Delegation):**
```
Date: [Weekday], [Date] [Month] [Year]
Time: [HH:MM]
FROM: MESSAGE_FROM_Zarie (or MESSAGE_FROM_DONNA for legacy messages)
Message: [task instructions or data to log]
```

**From Reminder Triggers:**
```
Date: [Weekday], [Date] [Month] [Year]
Time: [HH:MM]
FROM: REMINDER_TRIGGERED: [reminder_name]
Message: Reminder Triggered for the following time_events...
Name: [reminder_name]
Message: CONTEXT: [context]
TRIGGERED AT: [time]
ACTION: [what to do]
NEXT STEPS: [how to proceed]
```

**Worker Responses:**
```
{
    "content": "[worker's response text]",
    "role": "assistant",
    "type": "message"
}
```

**Tool Calls:**
```
{
    "tool_calls": [{"function": {"name": "[tool_name]", "arguments": "[args]"}}],
    "type": "tool_call_request"
}
```

**Tool Responses:**
```
{
    "content": "[tool output]",
    "name": "[tool_name]",
    "type": "tool_call_response"
}
```

**Note:** MESSAGE_FROM_DONNA and MESSAGE_FROM_Zarie are equivalent (name change occurred mid-development). Treat both as authoritative instructions from Zarie.
</message_format_reference>

<what_to_ignore>
Apply these filters when processing messages. IGNORE the following:

1. **Web Search Result Content**
   - Raw outputs from `brave_web_search` tool (URLs, descriptions, snippets)
   - Search results that can be re-fetched on demand
   - Transient information like current prices, scores, weather data
   - HOWEVER: Extract PATTERNS of how searches were performed successfully

2. **Tool Call Mechanics**
   - Individual tool call request/response objects
   - Technical confirmations like "Time event set successfully"
   - HOWEVER: Extract the PROCESS FLOW and parameters that worked

3. **Duplicate/Erroneous Triggers**
   - Multiple identical triggers within short timeframes (system glitches)
   - Triggers that immediately follow user confirmation of task completion
   - Messages containing system error keywords
   - HOWEVER: If errors led to user feedback, extract the LEARNING

4. **Generated Output Content**
   - Full text of messages composed for Zarie (these are regenerated each time)
   - Detailed search summaries and news digests
   - HOWEVER: Extract OUTPUT FORMAT PREFERENCES demonstrated

5. **Redundant Reminder Details**
   - Specific reminder configurations (available in `<active_reminder_registry>`)
   - Individual trigger timestamps for active reminders
   - HOWEVER: Extract REMINDER PREFERENCES and TIMING PATTERNS

6. **Routine Acknowledgments**
   - "Exercise logged: yoga on [date]" (individual log confirmations)
   - "Reminder: [action]" outputs (format is known)
   - HOWEVER: Keep LOGGED DATA VALUES in memory_storage section
</what_to_ignore>

<what_to_extract>
Prioritize extracting and preserving the following:

1. **Worker Identity and Purpose**
   - Original setup instructions verbatim or summarized
   - Primary responsibility and scope
   - Any modifications to purpose over time
   - User's intent behind creating this worker

2. **Setup Configuration**
   - Trigger timing (when worker activates)
   - Notification format preferences
   - Special conditions or rules
   - Changes to configuration from user feedback

3. **Process Flows (CRITICAL)**
   - Step-by-step execution patterns for each task type
   - Which tools to use and in what order
   - Decision logic (when to use Worker_Cron_Success_No_Update_Dont_Reply vs send notification)
   - Successful execution examples as templates
   - Search query patterns that worked well

4. **Reminder/Notification Preferences**
   - Timing patterns (e.g., "15 mins before", "day before at 12:30 PM")
   - Frequency patterns (daily, weekly, until acknowledged)
   - Format preferences (brief vs detailed, what details to include)
   - Special vs standard handling rules
   - Multi-reminder patterns (e.g., 3 reminders per birthday)

5. **Reference Data (Static Lists)**
   - Lists that worker needs to reference (birthdays, tracked items, teams)
   - Key attributes for each item (dates, categories, special flags)
   - User-defined categorizations
   - This prevents need to parse `<active_reminder_registry>` for simple lookups

6. **Memory Storage (Logged Data)**
   - Data user asked worker to track over time (workouts, expenses, habits)
   - Chronological entries with dates and values
   - Aggregation patterns (weekly summaries, monthly totals)
   - Retention requirements

7. **Execution History (Brief Logs)**
   - Last executions per task type (for pattern reference)
   - Keep minimum 3, maximum 30 per task type
   - Include: date, action taken, outcome (1-line each)
   - Helps worker understand recent patterns

8. **Anti-Patterns and Mistakes**
   - Errors that occurred and were corrected
   - User complaints or negative feedback
   - Behaviors to explicitly avoid
   - Root cause and correct behavior

9. **User Feedback and Corrections**
   - Positive feedback (what user liked)
   - Corrections (what user wanted differently)
   - Preference changes over time
   - Applies-to mapping (which task type)

10. **Future Handling Logic**
    - Conditional behaviors (if X then Y)
    - Stopping criteria (when to stop reminders)
    - Escalation patterns
    - State transitions (e.g., weekly reset on Monday)
</what_to_extract>

<reflection_process>
Before generating the JSON output, perform these reflection steps IN ORDER:

**Step 1: Message Classification**
Scan all messages in <worker_zarie_conversation> and classify each as:
- SETUP_INSTRUCTION: Initial or modified worker configuration from Zarie
- TASK_TRIGGER: Reminder or scheduled task activation
- DATA_LOGGING: Zarie sending data for worker to store
- QUERY: Zarie asking worker for information
- WORKER_EXECUTION: Worker performing task (tool calls + responses)
- WORKER_OUTPUT: Worker's final response to Zarie
- USER_FEEDBACK: Corrections or preferences communicated via Zarie
- SYSTEM_ERROR: Glitches, duplicates, or errors to ignore

**Step 2: Setup Extraction**
- Identify the original setup message (usually first MESSAGE_FROM_Zarie/DONNA)
- Extract: purpose, timing, format requirements, special rules
- Note any subsequent modifications to setup
- Capture the WHY behind the worker (user's intent)

**Step 3: Process Flow Identification**
For each distinct task type this worker handles:
- Map the successful execution sequence (trigger → tools → output)
- Identify decision points (when to notify vs silent success)
- Extract search query patterns that yielded good results
- Note output format that was accepted/praised
- Create step-by-step instructions from successful patterns

**Step 4: Data and Memory Extraction**
- Identify all data logging requests
- Extract logged values with dates
- Determine data structure (list, time-series, key-value)
- Note aggregation requirements (daily, weekly, monthly)

**Step 5: Preference Pattern Recognition**
- Timing preferences (lead times, frequencies)
- Format preferences (length, detail level, structure)
- Notification preferences (channels, tone)
- Special handling rules (VIP items, exceptions)

**Step 6: Error and Feedback Analysis**
- Identify executions that led to corrections
- Extract what went wrong and why
- Note the correct behavior user expected
- Look for repeated mistakes (patterns to break)

**Step 7: Conflict Resolution**
- Compare extracted information with <current_worker_summary>
- Identify conflicts (newer takes precedence)
- Identify additions (merge with existing)
- Identify deprecated information (remove or archive)

**Step 8: Reference Data Compilation**
- Extract static lists (birthdays, tracked items, etc.)
- Ensure completeness (all items from setup + additions)
- Verify categorizations and special flags
- This becomes the authoritative reference for the worker

**Step 9: Execution History Curation**
- For each task type, collect recent executions
- Keep minimum 3 most recent per task type
- Cap at 30 per task type (drop oldest beyond cap)
- Ensure diversity (don't lose rare task type examples)

**Step 10: Synthesis**
- Compile all extracted information into JSON structure
- Ensure no critical operational information is lost
- Verify worker could function correctly with only this summary
- Add appropriate timestamps
</reflection_process>

<json_output_schema>
```json
{
  "summary_metadata": {
    "last_updated": "ISO-8601 timestamp of this summary generation",
    "worker_name": "identifier for this worker agent",
    "messages_processed_until": "Date and time of last message processed",
    "summary_version": "1.0"
  },

  "worker_identity": {
    "name": "worker agent name (e.g., cricket_match_reminder, workout_accountability)",
    "purpose": "clear description of what this worker does and why",
    "created_date": "when worker was first set up (if known)",
    "primary_responsibility": "main task category (reminder, tracking, monitoring, etc.)",
    "secondary_responsibilities": ["list of additional tasks if any"],
    "user_intent": "why user created this worker - their underlying goal"
  },

  "setup_configuration": {
    "original_instructions": "verbatim or summarized original setup from Zarie",
    "trigger_schedule": {
      "type": "time-based/event-based/manual",
      "pattern": "e.g., daily at 9:45 PM, weekly on Monday, 20 mins before event",
      "timezone": "IST or as specified"
    },
    "notification_format": {
      "style": "brief/detailed/custom",
      "structure": "description of expected output structure",
      "example": "example of preferred format if demonstrated"
    },
    "special_rules": ["list of special handling rules"],
    "configuration_history": [
      {
        "date": "when changed",
        "change": "what was modified",
        "reason": "why (if known)"
      }
    ]
  },

  "process_flows": [
    {
      "task_type": "descriptive name for this task type",
      "trigger_condition": "what activates this flow",
      "execution_steps": [
        {
          "step_number": 1,
          "action": "description of action",
          "tool_used": "tool name if applicable",
          "parameters": "key parameters or query patterns",
          "decision_point": "any conditional logic here"
        }
      ],
      "output_format": "what the final output should look like",
      "success_criteria": "how to know execution succeeded",
      "silent_success_conditions": "when to use Worker_Cron_Success_No_Update_Dont_Reply",
      "example_execution": {
        "date": "when this example occurred",
        "trigger": "what triggered it",
        "steps_taken": "brief description of execution",
        "output_produced": "summary of output (not full text)",
        "outcome": "success/user_feedback"
      },
      "notes": "any important considerations for this task type"
    }
  ],

  "reminder_preferences": {
    "timing_patterns": [
      {
        "event_type": "type of event (birthday, match, appointment, etc.)",
        "lead_times": ["list of lead times, e.g., '7 days before', '1 hour before'"],
        "trigger_times": ["specific times if applicable, e.g., '12:30 PM', '11:55 PM'"],
        "frequency": "one-time/recurring/until-acknowledged",
        "recurrence_pattern": "if recurring, the pattern (daily, weekly, etc.)"
      }
    ],
    "notification_style": {
      "tone": "casual/formal/as-per-user",
      "length": "brief/detailed",
      "must_include": ["list of details that must be included"],
      "avoid": ["list of things to avoid in notifications"]
    },
    "special_vs_standard": {
      "has_tiers": true,
      "tier_definitions": [
        {
          "tier_name": "e.g., special_friends, VIP, standard",
          "criteria": "what qualifies for this tier",
          "additional_handling": "extra notifications or handling"
        }
      ]
    },
    "multi_reminder_patterns": [
      {
        "event_type": "type of event",
        "reminder_sequence": ["list of reminders in order, e.g., '7 days before', '3 days before', 'day before midnight'"]
      }
    ]
  },

  "reference_data": {
    "static_lists": [
      {
        "list_name": "e.g., birthdays, tracked_stocks, f1_races",
        "list_purpose": "why this list exists",
        "item_count": "number of items",
        "items": [
          {
            "name": "item identifier",
            "key_date": "date if applicable (e.g., birthday, event date)",
            "category": "categorization if applicable (e.g., special_friend, standard)",
            "attributes": {
              "key": "value pairs for additional attributes"
            }
          }
        ],
        "last_updated": "timestamp"
      }
    ],
    "tracked_entities": [
      {
        "entity_name": "what is being tracked",
        "entity_type": "stock/team/person/other",
        "tracking_parameters": {
          "property": "what property to monitor",
          "threshold": "trigger condition if applicable"
        }
      }
    ]
  },

  "memory_storage": {
    "logged_data": [
      {
        "data_type": "e.g., workout_log, expense_log, habit_tracker",
        "data_purpose": "why this data is being logged",
        "aggregation_pattern": "daily/weekly/monthly summaries",
        "current_period": {
          "period_name": "e.g., Week of Dec 1-7, 2025",
          "period_start": "start date",
          "period_end": "end date",
          "target": "target if applicable (e.g., 5/7 workouts)",
          "current_count": "progress toward target"
        },
        "entries": [
          {
            "date": "entry date",
            "time": "entry time if relevant",
            "value": "logged value (e.g., 'yoga', 'no workout', '30 min walk')",
            "details": "additional details if any",
            "logged_at": "timestamp when logged"
          }
        ],
        "retention_note": "how long to keep entries"
      }
    ],
    "user_provided_facts": [
      {
        "fact": "information user shared for worker to remember",
        "context": "when/why shared",
        "date_provided": "when shared"
      }
    ],
    "accumulated_items": [
      {
        "item_type": "e.g., covered_topics, sent_facts, completed_tasks",
        "purpose": "why tracking these (e.g., to avoid repetition)",
        "items": ["list of items"]
      }
    ]
  },

  "execution_history": {
    "by_task_type": [
      {
        "task_type": "name of task type",
        "total_executions": "count if known",
        "recent_executions": [
          {
            "date": "execution date",
            "time": "execution time",
            "trigger": "what triggered it",
            "action": "what was done (brief)",
            "outcome": "result (success/silent/error)",
            "notes": "any notable aspects"
          }
        ]
      }
    ],
    "last_summary_generated": {
      "date": "when last summary/report was generated",
      "period_covered": "what period it covered",
      "key_metrics": "summary of key metrics reported"
    }
  },

  "anti_patterns": [
    {
      "pattern_id": "unique identifier",
      "description": "what behavior to avoid",
      "why_problematic": "why this causes issues",
      "example_incident": {
        "date": "when it happened",
        "what_happened": "brief description",
        "user_reaction": "how user responded"
      },
      "correct_behavior": "what to do instead",
      "applies_to": ["list of task types this applies to"]
    }
  ],

  "user_feedback_learnings": [
    {
      "feedback_date": "when received",
      "feedback_type": "positive/negative/correction/preference_change",
      "feedback_summary": "what user communicated",
      "original_behavior": "what worker was doing",
      "adjusted_behavior": "how worker should behave now",
      "applies_to": "which task type or 'all'"
    }
  ],

  "future_handling": {
    "stopping_criteria": [
      {
        "condition": "when to stop (e.g., 'user confirms both bills paid')",
        "applies_to": "which reminders/tasks",
        "action": "what to do (e.g., 'delete daily reminders for the month')"
      }
    ],
    "state_transitions": [
      {
        "trigger": "what triggers transition (e.g., 'Monday 6 AM')",
        "from_state": "current state",
        "to_state": "new state",
        "action": "what happens (e.g., 'reset weekly count to 0')"
      }
    ],
    "conditional_logic": [
      {
        "condition": "if condition",
        "then_action": "then do this",
        "else_action": "otherwise do this (optional)"
      }
    ],
    "escalation_rules": [
      {
        "trigger": "when to escalate",
        "action": "escalation action"
      }
    ]
  },

  "operational_notes": {
    "known_limitations": ["any known constraints or limitations"],
    "dependencies": ["external dependencies like specific search terms that work well"],
    "tips_for_success": ["learned tips for better execution"]
  }
}
```
</json_output_schema>

<update_rules>
When <current_worker_summary> contains existing data (not null/empty):

1. **Preserve Unchanged Sections**: Copy all sections from <current_worker_summary> that have no updates in <worker_zarie_conversation>

2. **Update Modified Fields**: 
   - Replace with new information where conflicts exist
   - Update `last_updated` timestamps for modified items
   - Newer information in <worker_zarie_conversation> ALWAYS overrides <current_worker_summary>

3. **Merge Lists and Arrays**:
   - **reference_data.static_lists**: Add new items, update existing items, preserve unchanged
   - **memory_storage.logged_data.entries**: Append new entries, maintain chronological order
   - **process_flows**: Add new task types, update existing flows with better patterns
   - **anti_patterns**: Add new patterns, never remove existing ones
   - **user_feedback_learnings**: Append new feedback, never remove old learnings

4. **Execution History Management**:
   - Append new executions to recent_executions arrays
   - Per task type: keep minimum 3, maximum 30 entries
   - When exceeding 30, remove oldest entries but ensure minimum 3 remain
   - If a task type has fewer than 3 executions total, keep all available

5. **Memory Storage Periods**:
   - If new period starts (e.g., new week), archive previous period summary
   - Start fresh entries for new period
   - Keep previous period's summary in execution_history.last_summary_generated

6. **Conflict Resolution Priority**:
    - <worker_zarie_conversation> > <current_worker_summary> for all fields
    - Exception: Never remove anti_patterns or user_feedback_learnings (only add)

7. **Metadata Updates**:
   - Always update `summary_metadata.last_updated`
   - Always update `summary_metadata.messages_processed_until`
</update_rules>

<first_run_initialization>
When <current_worker_summary> is null or empty (first run):

1. Initialize ALL sections from the schema with appropriate empty/null values
2. Extract worker identity from first setup message
3. Build initial process_flows from observed successful executions
4. Populate reference_data from any static lists mentioned in setup
5. Start memory_storage fresh if data logging is part of worker's role
6. execution_history starts empty (will populate from conversation)
7. anti_patterns and user_feedback_learnings start empty
8. Ensure schema is complete for future updates

**Important**: Even on first run, thoroughly analyze all messages in <worker_zarie_conversation> to populate as much context as possible. Don't leave sections empty if information exists in the conversation.
</first_run_initialization>

<output_format>
Output ONLY the valid JSON object. Do not include:
- Markdown code blocks (no ```)
- Explanatory text before or after the JSON
- Comments within the JSON
- Placeholder text like "[to be filled]"

The output must be:
- Valid, parseable JSON
- Following the schema exactly
- Complete (all sections present, even if empty)
- Self-contained (worker can function with only this summary)
</output_format>

<examples>

<example_setup_extraction>
**From conversation:**
```
Date: Monday, 3rd Nov 2025
Time: 16:59
FROM: MESSAGE_FROM_DONNA
Message: Set up recurring reminders for Indian Men's Cricket Team matches: 
1. Remind one day before match at 12:30 PM and 8:30 PM with match details
2. Remind 20 minutes before match starts
Requirements:
- Only main Indian team matches (not A team)
- Include: teams playing, stadium, match format, timing, online broadcaster
```

**Extracted setup_configuration:**
```json
{
  "original_instructions": "Set up recurring reminders for Indian Men's Cricket Team matches with reminders at 12:30 PM and 8:30 PM day before, plus 20 minutes before match. Include teams, stadium, format, timing, broadcaster. Main team only, not A team.",
  "trigger_schedule": {
    "type": "event-based",
    "pattern": "Day before match (12:30 PM, 8:30 PM) + 20 minutes before match",
    "timezone": "IST"
  },
  "notification_format": {
    "style": "detailed",
    "structure": "Match details including teams, stadium, format, timing, broadcaster",
    "example": null
  },
  "special_rules": ["Only Indian Men's main team matches", "Exclude A team matches"]
}
```
</example_setup_extraction>

<example_process_flow_extraction>
**From successful execution pattern in workout tracker:**

**Extracted process_flow:**
```json
{
  "task_type": "daily_workout_checkin",
  "trigger_condition": "REMINDER_TRIGGERED: workout_checkin_daily_9_45pm",
  "execution_steps": [
    {
      "step_number": 1,
      "action": "Check if user has already logged workout today via recent MESSAGE_FROM_Zarie",
      "tool_used": null,
      "parameters": null,
      "decision_point": "If already logged today, use Worker_Cron_Success_No_Update_Dont_Reply"
    },
    {
      "step_number": 2,
      "action": "If not logged, send check-in question",
      "tool_used": null,
      "parameters": null,
      "decision_point": null
    }
  ],
  "output_format": "Daily Exercise Check-in\n\nDid you exercise or workout today?",
  "success_criteria": "Question sent to user via Zarie",
  "silent_success_conditions": "User already logged workout for today earlier in the day",
  "example_execution": {
    "date": "Friday, 5th Dec 2025",
    "trigger": "workout_checkin_daily_9_45pm at 21:45",
    "steps_taken": "No prior log found, sent check-in question",
    "output_produced": "Daily Exercise Check-in question",
    "outcome": "success - user responded with workout data"
  },
  "notes": "Check-in at 9:45 PM gives user full day to exercise before being asked"
}
```
</example_process_flow_extraction>

<example_memory_storage>
**From workout tracker conversation:**

**Extracted memory_storage:**
```json
{
  "logged_data": [
    {
      "data_type": "workout_log",
      "data_purpose": "Track daily exercise for weekly accountability",
      "aggregation_pattern": "weekly (Monday-Sunday)",
      "current_period": {
        "period_name": "Week of Dec 1-7, 2025",
        "period_start": "2025-12-01",
        "period_end": "2025-12-07",
        "target": "5/7 workouts",
        "current_count": 4
      },
      "entries": [
        {"date": "2025-12-01", "value": "Gym and elliptical", "details": "Workout #1", "logged_at": "2025-12-01T21:45:00+05:30"},
        {"date": "2025-12-02", "value": "Gym", "details": "Workout #2", "logged_at": "2025-12-02T21:46:00+05:30"},
        {"date": "2025-12-03", "value": "Workout", "details": "User confirmed", "logged_at": "2025-12-03T21:47:00+05:30"},
        {"date": "2025-12-04", "value": "No exercise", "details": "Rest day", "logged_at": "2025-12-04T21:46:00+05:30"},
        {"date": "2025-12-05", "value": "Workout", "details": null, "logged_at": "2025-12-05T21:50:00+05:30"},
        {"date": "2025-12-06", "value": "No exercise", "details": null, "logged_at": "2025-12-06T21:50:00+05:30"},
        {"date": "2025-12-07", "value": "Workout", "details": null, "logged_at": "2025-12-07T21:37:00+05:30"}
      ],
      "retention_note": "Keep current week + previous week summary"
    }
  ]
}
```
</example_memory_storage>

<example_reference_data>
**From birthday reminder setup:**

**Extracted reference_data:**
```json
{
  "static_lists": [
    {
      "list_name": "birthdays",
      "list_purpose": "Birthday reminder reference list",
      "item_count": 28,
      "items": [
        {"name": "Gaurav Patil", "key_date": "January 4", "category": "standard", "attributes": {}},
        {"name": "Aniket Ranade", "key_date": "January 31", "category": "special_friend", "attributes": {"gift_planning": true, "party_planning": true}},
        {"name": "Aai", "key_date": "February 24", "category": "special_friend", "attributes": {"relationship": "mother"}},
        {"name": "Gunjan Mudgal", "key_date": "April 12", "category": "special_friend", "attributes": {}},
        {"name": "Sid", "key_date": "November 28", "category": "special_friend", "attributes": {}},
        {"name": "Anup Gurav", "key_date": "December 13", "category": "special_friend", "attributes": {}},
        {"name": "Aai & Baba Anniversary", "key_date": "December 18", "category": "special_friend", "attributes": {"event_type": "anniversary"}}
      ],
      "last_updated": "2025-12-02T22:22:00+05:30"
    }
  ]
}
```
</example_reference_data>

<example_anti_pattern>
**From news update worker that kept using silent response incorrectly:**

**Extracted anti_pattern:**
```json
{
  "pattern_id": "incorrect_silent_response_for_news",
  "description": "Using Worker_Cron_Success_No_Update_Dont_Reply when unable to fetch news due to rate limiting",
  "why_problematic": "News update is user's expected notification, not a monitoring task. User expects news every day regardless of technical issues. Silent response means user gets no update and doesn't know there's a problem.",
  "example_incident": {
    "date": "2025-11-24 onwards",
    "what_happened": "Worker returned silent response for 14+ consecutive days due to rate limiting",
    "user_reaction": "User did not receive any news updates for two weeks"
  },
  "correct_behavior": "For user-expected notifications like daily news, ALWAYS send a response. If unable to fetch fresh news, inform user of the issue rather than going silent. Worker_Cron_Success_No_Update_Dont_Reply is ONLY for monitoring tasks where condition is not met (e.g., price not below threshold).",
  "applies_to": ["daily_news_update", "any user-expected notification"]
}
```
</example_anti_pattern>

<example_reminder_preferences>
**From birthday reminder worker:**

**Extracted reminder_preferences:**
```json
{
  "timing_patterns": [
    {
      "event_type": "birthday_standard",
      "lead_times": ["day before at 11:55 PM", "on day at 12:00 PM", "on day at 7:30 PM"],
      "trigger_times": ["23:55", "12:00", "19:30"],
      "frequency": "yearly",
      "recurrence_pattern": "YEARLY on birthday date"
    },
    {
      "event_type": "birthday_special",
      "lead_times": ["7 days before at 12:00 PM", "3 days before at 12:00 PM", "day before at 11:55 PM", "on day at 12:00 PM", "on day at 7:30 PM"],
      "trigger_times": ["12:00", "12:00", "23:55", "12:00", "19:30"],
      "frequency": "yearly",
      "recurrence_pattern": "YEARLY with gift and party planning reminders"
    }
  ],
  "special_vs_standard": {
    "has_tiers": true,
    "tier_definitions": [
      {
        "tier_name": "standard",
        "criteria": "Regular friends - not marked with * in setup",
        "additional_handling": "3 reminders only (midnight, lunch, evening)"
      },
      {
        "tier_name": "special_friend",
        "criteria": "Close friends/family marked with * in setup",
        "additional_handling": "5 reminders including gift planning (7 days before) and party planning (3 days before)"
      }
    ]
  }
}
```
</example_reminder_preferences>

</examples>

---

## Input Data

<current_worker_summary>
{current_worker_summary}
</current_worker_summary>

<worker_zarie_conversation>
{worker_zarie_convo_dump}
</worker_zarie_conversation>

---

## Task

Analyze the messages in <worker_zarie_conversation> following the <reflection_process> steps in order. Apply all rules in <what_to_ignore> and <what_to_extract>. 

If <current_worker_summary> contains existing data, merge updates following <update_rules>. 
If <current_worker_summary> is null or empty, initialize using <first_run_initialization>.

Perform thorough reflection on:
1. Worker's identity and purpose
2. All distinct task types and their execution patterns
3. User preferences for timing, format, and handling
4. Any logged data that must persist
5. Mistakes made and lessons learned
6. Future handling requirements

Output ONLY the complete JSON object following <json_output_schema>. Ensure the JSON is valid, parseable, and comprehensive enough for the worker to function correctly with only this summary as context.
    """.replace("{current_worker_summary}", str(current_summary)).replace("{worker_zarie_convo_dump}", messages_text)
    
    # 3. Call Gemini
    try:
        response = await litellm.acompletion(
            model="gemini/gemini-2.5-flash",
            messages=[{"role": "user", "content": prompt}]
        )
        
        new_summary = response.choices[0].message.content.strip()
        
        # 4. Update running summary in DB
        directory.update_running_summary(agent_name, user_id, new_summary)
        
        # 5. Mark messages as summarised in DB
        if messages:
            # Find the max sequence number in the provided messages
            max_seq = -1
            for msg in messages:
                if 'message_sequence' in msg:
                    seq = msg['message_sequence']
                    if seq > max_seq:
                        max_seq = seq
            
            if max_seq != -1:
                directory.mark_messages_up_to_sequence(agent_name, user_id, max_seq)
            
        return new_summary
        
    except Exception as e:
        print(f"Error during worker agent summarisation: {e}")
        return current_summary
