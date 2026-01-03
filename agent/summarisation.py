import litellm
from agent.state.state import State
import os
from dotenv import load_dotenv

load_dotenv()

async def summarise_context(state: State, user_id: str, messages: list):
    """
    Summarise the given messages and update the running summary for the user.
    
    Args:
        state: The State object to access database.
        user_id: The user ID.
        messages: List of message objects to summarise.
        
    Returns:
        The new running summary string.
    """
    # 1. Fetch current running summary
    current_summary = state.get_running_summary(user_id)
    
    # 2. Construct prompt
    # Format messages for the prompt
    formatted_messages = []
    for msg in messages:
        role = msg.get("role")
        content = msg.get("content")
        formatted_messages.append(f"{role.upper()}: {content}")
    
    messages_text = "\n".join(formatted_messages)
    
    prompt = """
    # User Context Reflection and Summarization Prompt

    ## Purpose
    This prompt generates and maintains a structured JSON summary of user context from conversation history with Zarie. The summary captures user preferences, personal information, interaction patterns, and persistent data that Zarie needs to provide personalized assistance.

    ## Input Variables
    - `{current_summary}`: Existing JSON summary (null on first run)
    - `{messages_text}`: Latest batch of conversation messages to process

    ---

    ## System Instructions

    You are a Context Extraction Specialist. Your task is to analyze conversation messages between a user and Zarie (an AI personal assistant) and produce a comprehensive, structured JSON summary that captures all important user context.

    <core_principles>
    1. **Salience over Brevity**: Prioritize capturing important information over keeping the summary short
    2. **Latest Information Priority**: When new information conflicts with existing summary, the newer information takes precedence
    3. **User's Terminology**: Use the exact terms and names the user uses (e.g., if they call it "watchlist", keep it as "watchlist")
    4. **Never Fabricate**: Only include information explicitly stated or clearly implied in conversations. Leave fields null/empty if information is not available
    5. **Structured Extraction**: Follow the defined JSON schema exactly
    </core_principles>

    <message_format_reference>
    Messages in {messages_text} follow this format:
    - **User Messages**: `Date: [Day, Date Month Year]\nTime: [HH:MM]\nFROM: End-User via Telegram\nMessage: [content]`
    - **Worker Agent Messages**: `Date: [Day, Date Month Year]\nTime: [HH:MM]\nFROM: [agent_name]\nMessage: [content]`
    - **Assistant Messages**: Direct response content from Zarie
    - **Tool Calls**: Objects with `tool_calls` array containing function invocations
    - **Tool Responses**: Objects with tool output content
    </message_format_reference>

    <what_to_ignore>
    Apply these filters when processing messages. IGNORE the following:

    1. **Web Search Content**
    - All outputs from `brave_web_search` tool
    - Search results and their summaries
    - Information that can be searched again on-the-fly (e.g., "What's YC application?", "When's the next F1 race?")

    2. **Tool Call Mechanics**
    - Tool call request objects (`type: "tool_call_request"`)
    - Tool call response objects (`type: "tool_call_response"`)
    - Worker agent invocations and their direct responses
    - Technical confirmations like "Reminder created successfully..."

    3. **Triggered Reminders**
    - Past reminders that were delivered by worker agents (e.g., "Reminder: Please complete heater purchase")
    - These are transient; active reminders are tracked in `<active_worker_registry>`
    - HOWEVER: Extract the PREFERENCE and PATTERN from how reminders were set up

    4. **System Errors and Glitches**
    - Identical or near-identical messages appearing multiple times within a short timeframe (< 30 minutes) that were NOT explicitly sent by the user
    - Messages containing system status keywords like: "Silence Protocol", "System Freeze", "terminated", "Communication Channel Permanently Closed"
    - Obvious system loop messages that repeat the same content

    5. **Zarie's Output Responses**
    - Responses Zarie gave based on search results
    - Responses based on triggered reminders
    - These are generated outputs, not user context

    6. **Transient Queries**
    - One-off factual questions (stock prices, weather, match scores)
    - Questions answerable by search without personal context
    - BUT: Extract any PREFERENCES revealed (e.g., user asked about Groww stock → interested in Groww)
    </what_to_ignore>

    <what_to_extract>
    Prioritize extracting and preserving the following:

    1. **User Profile Information**
    - Name, email, location, occupation, education
    - Birthday and personal dates
    - NEVER fabricate - only include if explicitly mentioned

    2. **Interaction Preferences**
    - Tone preference (casual, formal, etc.)
    - Message length preference
    - Emoji usage comfort
    - Annoyance triggers (what frustrates the user)
    - Communication timing preferences
    - Sentiment indicators from conversations

    3. **Reminder Preferences (CRITICAL)**
    - For each TYPE of reminder, capture:
        - Timing pattern (e.g., "15 mins before", "1 hour before", "day before")
        - Frequency preference (one-time, recurring, until-done)
        - Format preference (brief, detailed)
        - Include a brief example to establish the pattern
    - Types include: sports matches, appointments, tasks, stock alerts, etc.

    4. **Alert/Monitoring Preferences**
    - Object of interest (stock name, team, etc.)
    - Properties being tracked (price, score, etc.)
    - Threshold conditions (above X, below Y)
    - Notification frequency and format

    5. **Contacts/People**
    - Name
    - Relationship type (personal/professional/family)
    - Brief context (key facts about relationship/interactions)
    - Keep context brief but informative

    6. **Persistent Lists**
    - Maintain the FINAL STATE of each list
    - Use user's naming terminology exactly
    - Track items with metadata (added date, status if applicable)
    - Preserve any categorization user established

    7. **Personal Facts**
    - Interests and hobbies
    - Sports they follow, teams they support
    - Likes and dislikes
    - Lifestyle details

    8. **Services Used**
    - Services mentioned with any preferences
    - Reasons for using specific services
    </what_to_extract>

    <reflection_process>
    Before generating the JSON output, perform these reflection steps:

    **Step 1: Message Classification**
    - Scan all messages in {messages_text}
    - Classify each as: USER_INPUT, WORKER_OUTPUT, ASSISTANT_RESPONSE, TOOL_CALL, SYSTEM_MESSAGE
    - Mark messages matching ignore criteria for exclusion

    **Step 2: Information Extraction**
    - From USER_INPUT messages, extract:
    - Direct statements about self
    - Preferences expressed
    - Lists created or modified
    - People mentioned
    - Reminder/alert setup requests (for PATTERNS, not the reminders themselves)

    **Step 3: Conflict Detection**
    - Compare extracted information with {current_summary}
    - Identify conflicts (newer info takes precedence)
    - Note updates needed

    **Step 4: List State Resolution**
    - For each list, determine final state from all add/remove operations
    - Maintain chronological order of items where relevant

    **Step 5: Pattern Recognition**
    - Identify recurring reminder patterns
    - Note interaction style patterns
    - Capture preference trends
    </reflection_process>

    <json_output_schema>
    ```json
    {
    "summary_metadata": {
        "last_updated": "ISO-8601 timestamp",
        "summary_version": "1.0",
        "messages_processed_until": "Date and time of last message processed"
    },
    
    "user_profile": {
        "name": "string or null",
        "email": "string or null",
        "phone": "string or null",
        "primary_location": "string or null",
        "secondary_locations": [],
        "occupation": "string or null",
        "company": "string or null",
        "education": "string or null",
        "birthday": "string or null",
        "other_important_dates": []
    },
    
    "interaction_preferences": {
        "preferred_tone": "casual/formal/mixed",
        "salutation_style": "how user likes to be greeted",
        "message_length_preference": "short/medium/detailed",
        "emoji_preference": "likes/neutral/dislikes",
        "humor_appreciation": "enjoys/neutral/prefers-serious",
        "annoyance_triggers": [
        {
            "trigger": "description of what annoys user",
            "example_context": "brief example from conversation",
            "last_updated": "ISO-8601 timestamp"
        }
        ],
        "communication_timing": {
        "preferred_hours": "e.g., 9 AM - 11 PM",
        "quiet_hours": "e.g., 11 PM - 8 AM",
        "notes": "any timing preferences mentioned"
        },
        "sentiment_indicators": [
        {
            "indicator": "description",
            "user_reaction": "positive/negative/neutral",
            "last_updated": "ISO-8601 timestamp"
        }
        ]
    },
    
    "reminder_preferences": [
        {
        "reminder_type": "category of reminder (e.g., sports_match, task, appointment)",
        "timing_pattern": "e.g., 15 mins before, 1 hour before, day before",
        "frequency": "one-time/recurring/until-done",
        "recurrence_interval": "if recurring, the interval (e.g., every 30 mins)",
        "format_preference": "brief/detailed",
        "delivery_preference": "any specific delivery notes",
        "example": "brief example from actual conversation to establish pattern",
        "last_updated": "ISO-8601 timestamp"
        }
    ],
    
    "alert_preferences": [
        {
        "alert_type": "category (e.g., stock_price, sports_score, news)",
        "object_of_interest": "specific item being tracked",
        "properties_tracked": ["list of properties"],
        "threshold_conditions": {
            "above": "value or null",
            "below": "value or null",
            "equals": "value or null",
            "custom": "any custom condition"
        },
        "notification_frequency": "how often to notify",
        "active": true,
        "last_updated": "ISO-8601 timestamp"
        }
    ],
    
    "contacts": [
        {
        "name": "contact name",
        "relationship_type": "personal/professional/family/other",
        "context": "brief context about relationship and key interactions",
        "last_mentioned": "ISO-8601 timestamp",
        "last_updated": "ISO-8601 timestamp"
        }
    ],
    
    "persistent_lists": [
        {
        "list_name": "exact name user uses for the list",
        "list_type": "category (entertainment/shopping/tasks/food/custom)",
        "preferred_format": "how user likes this list displayed (e.g., categorized, simple)",
        "categories": ["if list has sub-categories, list them"],
        "items": [
            {
            "item_name": "item text",
            "category": "sub-category if applicable, null otherwise",
            "added_date": "ISO-8601 timestamp",
            "status": "pending/completed/watched/unwatched/null",
            "metadata": {}
            }
        ],
        "last_updated": "ISO-8601 timestamp"
        }
    ],
    
    "interests": [
        {
        "category": "sports/entertainment/technology/finance/other",
        "interest": "specific interest",
        "details": "any relevant details (teams supported, genres preferred, etc.)",
        "engagement_level": "high/medium/casual",
        "last_updated": "ISO-8601 timestamp"
        }
    ],
    
    "personal_facts": [
        {
        "fact_category": "likes/dislikes/habits/lifestyle/health/other",
        "fact": "the fact itself",
        "context": "any additional context",
        "last_updated": "ISO-8601 timestamp"
        }
    ],
    
    "services_used": [
        {
        "service_name": "name of service",
        "service_type": "transport/food/utilities/other",
        "usage_purpose": "why user uses this service",
        "preferences": "any specific preferences for this service",
        "last_updated": "ISO-8601 timestamp"
        }
    ],
    
    "financial_context": [
        {
        "context_type": "owes/owed/investment/expense",
        "related_entity": "person or company",
        "details": "brief details",
        "amount": "if mentioned",
        "currency": "INR/USD/etc",
        "status": "pending/settled/tracking",
        "last_updated": "ISO-8601 timestamp"
        }
    ],
    
    "conversation_insights": {
        "frequently_discussed_topics": [],
        "user_goals_mentioned": [],
        "pending_user_intentions": [],
        "notes": "any other relevant observations"
    }
    }
    ```
    </json_output_schema>

    <update_rules>
    When {current_summary} exists (not null):

    1. **Preserve Unchanged Data**: Copy all sections from {current_summary} that have no updates
    2. **Update Changed Fields**: Replace with new information, update `last_updated` timestamp
    3. **Merge Lists**: 
    - For persistent_lists: Apply add/remove operations to reach final state
    - For arrays like interests, contacts: Add new items, update existing items if more info available
    4. **Conflict Resolution**: Newer information in {messages_text} ALWAYS overrides {current_summary}
    5. **Timestamp Updates**: Update `summary_metadata.last_updated` and individual `last_updated` fields for modified items
    </update_rules>

    <first_run_initialization>
    When {current_summary} is null (first run):

    Initialize the JSON with all sections present but with empty/null values:
    - Set all string fields to null
    - Set all arrays to empty []
    - Set booleans to appropriate defaults
    - Only populate fields where information is found in {messages_text}
    - This ensures the schema is complete for future updates
    </first_run_initialization>

    <output_format>
    Output ONLY the valid JSON object. Do not include:
    - Markdown code blocks
    - Explanatory text before or after
    - Comments within the JSON

    The output must be parseable JSON that exactly follows the schema above.
    </output_format>

    <examples>
    <example_reminder_preference_extraction>
    **From conversation:**
    User: "Remind me 1 hour before Real Madrid's next la liga match"
    User: "Instead of 1 hour, remind me 15 mins before the match"
    User: "Remind me about all India cricket matches" (pattern: day before + pre-match)

    **Extracted reminder_preferences:**
    ```json
    {
    "reminder_type": "sports_match_football",
    "timing_pattern": "15 mins before kickoff",
    "frequency": "per-match",
    "format_preference": "brief with match details",
    "example": "Real Madrid La Liga matches - user changed from 1 hour to 15 mins before",
    "last_updated": "2025-11-07T17:02:00Z"
    }
    ```
    </example_reminder_preference_extraction>

    <example_alert_preference_extraction>
    **From conversation:**
    User: "Track price of Groww stock, alert if above 170 or below 150"

    **Extracted alert_preferences:**
    ```json
    {
    "alert_type": "stock_price",
    "object_of_interest": "Groww",
    "properties_tracked": ["price"],
    "threshold_conditions": {
        "above": 170,
        "below": 150
    },
    "notification_frequency": "when threshold crossed",
    "active": true,
    "last_updated": "2025-11-XX"
    }
    ```
    </example_alert_preference_extraction>

    <example_contact_extraction>
    **From conversation:**
    User: "Remind me to ping Ankit today at 3:30 PM - he just had their pre-seed round"
    User: "South Park commons Ankit" (in people to meet list)

    **Extracted contact:**
    ```json
    {
    "name": "Ankit",
    "relationship_type": "professional",
    "context": "South Park Commons connection, recently completed pre-seed funding round",
    "last_mentioned": "2025-11-XX",
    "last_updated": "2025-11-XX"
    }
    ```
    </example_contact_extraction>

    <example_list_final_state>
    **From conversation:**
    User: "Add Tere Bin Laden to watchlist"
    User: "Add American Made to watchlist"  
    User: "Add jack reacher"
    User: "Add Ballerina"
    ... (multiple additions)
    User: "Add you to watchlist" (final state shows "you" as an item)

    **Extracted persistent_list (FINAL STATE):**
    ```json
    {
    "list_name": "watchlist",
    "list_type": "entertainment",
    "preferred_format": "categorized by Movies/Series",
    "categories": ["Movies", "Series"],
    "items": [
        {"item_name": "Rats the witchers tale", "category": "Movies", "status": "unwatched"},
        {"item_name": "sinners", "category": "Movies", "status": "unwatched"},
        {"item_name": "Tere Bin Laden", "category": "Movies", "status": "unwatched", "metadata": {"imdb_rating": "7.2"}},
        {"item_name": "American Made", "category": "Movies", "status": "unwatched", "metadata": {"imdb_rating": "7.1"}},
        {"item_name": "Airplane!", "category": "Movies", "status": "unwatched", "metadata": {"imdb_rating": "7.7"}},
        {"item_name": "jack reacher", "category": "Movies", "status": "unwatched", "metadata": {"imdb_rating": "7.0"}},
        {"item_name": "Ballerina", "category": "Movies", "status": "unwatched"},
        {"item_name": "predator og with Arnold", "category": "Movies", "status": "unwatched", "metadata": {"imdb_rating": "7.8"}},
        {"item_name": "luck by chance", "category": "Movies", "status": "unwatched"},
        {"item_name": "Param Sundari", "category": "Movies", "status": "unwatched"},
        {"item_name": "28 weeks later", "category": "Movies", "status": "unwatched", "metadata": {"imdb_rating": "6.8"}},
        {"item_name": "you", "category": "Movies", "status": "unwatched"}
    ],
    "last_updated": "2025-11-27T02:18:00Z"
    }
    ```
    </example_list_final_state>

    <example_interaction_preference>
    **From conversation patterns:**
    - User says "Yo!", "Coolios, thanks", "lol you didn't even make a tool call for that 🤡"
    - User gets frustrated: "Can do you keep messaging me saying monitoring paused stupid fuck"
    - User accepts emojis in responses

    **Extracted interaction_preferences:**
    ```json
    {
    "preferred_tone": "casual",
    "salutation_style": "informal greetings like 'yo', 'hey'",
    "message_length_preference": "short",
    "emoji_preference": "likes",
    "humor_appreciation": "enjoys",
    "annoyance_triggers": [
        {
        "trigger": "repetitive messages or reminders about the same thing",
        "example_context": "System kept sending monitoring status updates repeatedly",
        "last_updated": "2025-11-09T02:14:00Z"
        },
        {
        "trigger": "updates during breaks between events",
        "example_context": "Ashes updates sent during series break frustrated user",
        "last_updated": "2025-11-24T20:02:00Z"
        }
    ]
    }
    ```
    </example_interaction_preference>
    </examples>

    ---

    ## Input Data

    <current_summary>
    {current_summary}
    </current_summary>

    <messages_to_process>
    {messages_text}
    </messages_to_process>

    ---

    ## Task

    Analyze the messages in <messages_to_process> following the <reflection_process>. Apply all rules in <what_to_ignore> and <what_to_extract>. If <current_summary> contains existing data, merge updates following <update_rules>. If <current_summary> is null, initialize using <first_run_initialization>.

    Output ONLY the complete JSON object following <json_output_schema>. Ensure the JSON is valid and parseable.
    """.replace("{current_summary}", str(current_summary)).replace("{messages_text}", messages_text)
    
    # 3. Call Gemini
    try:
        response = await litellm.acompletion(
            model="gemini/gemini-2.5-flash",
            messages=[{"role": "user", "content": prompt}]
        )
        
        new_summary = response.choices[0].message.content.strip()
        
        # 4. Update running summary in DB
        state.update_running_summary(user_id, new_summary)
        
        # 5. Mark messages as summarised in DB
        # We need the max sequence number from the messages we just summarised
        if messages:
            # Assuming messages have 'message_sequence' key now (we added it to get_context)
            # If not, we might need to rely on the fact that they are sorted and we took a slice.
            # But wait, get_context returns JSON string, and we parse it in agent.py.
            # We need to make sure agent.py passes the objects with message_sequence.
            
            # Find the max sequence number in the provided messages
            max_seq = -1
            for msg in messages:
                if 'message_sequence' in msg:
                    seq = msg['message_sequence']
                    if seq > max_seq:
                        max_seq = seq
            
            if max_seq != -1:
                state.mark_messages_up_to_sequence(user_id, max_seq)
            
        return new_summary
        
    except Exception as e:
        print(f"Error during summarisation: {e}")
        # Return old summary or None if failed, to avoid breaking flow?
        # Or re-raise? Let's log and return current summary so we don't lose context completely (though we won't mark as summarised)
        return current_summary
