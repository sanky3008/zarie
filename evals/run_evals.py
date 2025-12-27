"""
Evaluation Runner for Zarie Agent System
=========================================
Runs multi-turn conversation evaluations using DeepEval.
Evaluates both Main Agent (Zarie) and Worker Agents.
"""

import os
import sys
import uuid
import json
import asyncio
import pandas as pd
import pytest
from datetime import datetime, timezone
from dateutil.parser import parse
from dotenv import load_dotenv

# Add project root to sys.path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent.agent import Agent
from agent.utils import MessageBuffer
from user_manager import create_or_update_user, get_user
from event_manager.time_event_manager import get_due_events, update_next_trigger, disable_event, update_event_status
from worker_agent.agent.agent import WorkerAgent
from run_scheduler import check_and_process_events

# DeepEval imports
from deepeval import evaluate
from deepeval.test_case import LLMTestCase, ConversationalTestCase, Turn, ToolCall, TurnParams
from deepeval.metrics import ConversationalGEval

load_dotenv()

# ============================================================================
# EVALUATION CRITERIA
# ============================================================================

MAIN_AGENT_CRITERIA = """
Evaluate Zarie's conversation handling and tool usage protocol.

ACKNOWLEDGMENT-FIRST PROTOCOL (Critical):
When user requests scheduling, automation, or web search:
1. MUST call send_message_to_user FIRST with a brief acknowledgment like "Setting that up" or "On it!"
2. THEN call invoke_worker_agent (for scheduling) or brave_web_search (for search)
3. THEN provide a natural, friendly confirmation to the user

NO ACKNOWLEDGMENT needed for:
- Simple greetings or conversation
- Checking context/memory only
- Processing worker agent trigger messages (FROM: {agent_name})

TOOL ARGUMENT VALIDATION:
- invoke_worker_agent must include: agent_name, purpose, and message with timezone context
- send_message_to_user message should be casual, under 15 words, no tool names

FINAL RESPONSE:
- Natural, friend-like tone matching user's style
- No technical jargon or mentions of tools/agents
- Appropriate confirmation of action taken

SCORING:
- PASS: Correct acknowledgment sequence → tool call → confirmation
- FAIL: Missing acknowledgment before invoke_worker_agent, robotic tone, or incorrect tool arguments
"""

WORKER_AGENT_CRITERIA = """
Evaluate a backend Worker Agent conversation. NOTE: In OpenAI message format, the worker's responses have role='assistant' - this is correct and expected.

WHAT TO EVALUATE:
1. Did the assistant call the appropriate tool (set_time_event, delete_time_event, or brave_web_search)?
2. Does the tool call input contain the necessary parameters?
3. Did the assistant provide a confirmation message after the tool executed?

EXPECTED BEHAVIOR:
- For reminder creation: Call set_time_event with reminder_name and next_trigger_timestamp in tool input
- For reminder trigger: Respond with a simple "Reminder: [action]" message
- Confirmations like "Created: reminder_name for [time]" are CORRECT backend format

SCORING:
- PASS: Appropriate tool called, parameters present in tool input, confirmation provided
- FAIL: Wrong tool, missing parameters, no confirmation
"""


EXPECTED_TOOLS_MAIN_AGENT = ["send_message_to_user", "invoke_worker_agent", "brave_web_search"]
EXPECTED_TOOLS_WORKER_AGENT = ["set_time_event", "delete_time_event", "brave_web_search"]


# ============================================================================
# HELPERS
# ============================================================================

def convert_messages_to_turns(messages: list) -> list[Turn]:
    """Convert agent messages (OpenAI format) to DeepEval Turn format."""
    turns = []
    i = 0
    while i < len(messages):
        msg = messages[i]
        role = msg.get('role')
        content = msg.get('content')
        
        if role == 'user':
            turns.append(Turn(role='user', content=content or ""))
            
        elif role == 'assistant':
            tool_calls_data = msg.get('tool_calls')
            if not tool_calls_data:
                # Pure text response
                turns.append(Turn(role='assistant', content=content or " "))
            else:
                # Tool call - look ahead for outputs
                final_tool_calls = []
                tool_details = []  # Build details as we process
                for tc in tool_calls_data:
                    tc_id = tc['id']
                    tc_name = tc['function']['name']
                    tc_args = tc['function']['arguments']
                    
                    # Find matching tool response
                    tc_output = None
                    for j in range(i + 1, len(messages)):
                        next_msg = messages[j]
                        if next_msg.get('role') == 'tool' and next_msg.get('tool_call_id') == tc_id:
                            tc_output = next_msg.get('content')
                            break
                    
                    # Format args as readable text so judge can evaluate
                    try:
                        args_dict = json.loads(tc_args)
                        tc_args_readable = ", ".join(f"{k}={v}" for k, v in args_dict.items())
                    except:
                        tc_args_readable = tc_args
                    
                    # Build tool detail string for content
                    tool_details.append(f"[Tool Call: {tc_name}({tc_args_readable})]")
                    
                    final_tool_calls.append(ToolCall(
                        name=tc_name,
                        input=tc_args_readable,
                        output=tc_output
                    ))
                
                # Include tool call details in content for judge visibility
                content_with_tools = (content or "") + "\n" + "\n".join(tool_details) if tool_details else content
                
                turns.append(Turn(
                    role='assistant',
                    content=content_with_tools.strip() or " ",
                    tools_called=final_tool_calls
                ))
        # Skip 'tool' role - already merged into assistant turns
        i += 1
    return turns


def save_trace(trace_dir: str, episode_id: str, run_id: str, expected_behavior: str, 
               main_trace: list, worker_traces: dict) -> str:
    """Save trace data to JSON file."""
    os.makedirs(trace_dir, exist_ok=True)
    trace_data = {
        "episode_id": episode_id,
        "run_id": run_id,
        "expected_behavior": expected_behavior.strip(),
        "main_agent_trace": main_trace,
        "worker_agent_traces": worker_traces
    }
    path = os.path.join(trace_dir, f"{episode_id}.json")
    with open(path, "w") as f:
        json.dump(trace_data, f, indent=2)
    return path


def extract_invoked_workers(messages: list) -> list[tuple[str, str]]:
    """Extract (agent_name, args_json) from invoke_worker_agent tool calls."""
    workers = []
    for msg in messages:
        if msg.get('role') == 'assistant' and msg.get('tool_calls'):
            for tc in msg['tool_calls']:
                if tc['function']['name'] == 'invoke_worker_agent':
                    try:
                        args = json.loads(tc['function']['arguments'])
                        agent_name = args.get('agent_name', 'unknown')
                        workers.append((agent_name, tc['function']['arguments']))
                    except json.JSONDecodeError:
                        pass
    return workers


# ============================================================================
# EVAL RUNNER
# ============================================================================

class EvalRunner:
    def __init__(self, dataset_path: str):
        self.dataset_path = dataset_path
        self.run_id = str(uuid.uuid4())[:8]
        self.df = pd.read_csv(dataset_path)
        
        self.agent = Agent()
        self.worker_agent = WorkerAgent()
        
        # Track invoked workers per episode: {episode_id: [(agent_name, scoped_user_id), ...]}
        self.invoked_workers: dict[str, list[tuple[str, str]]] = {}
        
        # Mock send_message_to_user for evals
        async def mock_send_message(user_id: str, message: str, **kwargs):
            return "Message sent successfully (Mock)"
        self.agent.tool_functions["send_message_to_user"] = mock_send_message
    
    def _scope_user_id(self, original_id: str, episode_id: str) -> str:
        """Create unique scoped user_id to isolate test data."""
        return f"{original_id}_{episode_id}_{self.run_id}"
    
    async def simulate_episode(self, episode_id: str) -> list[ConversationalTestCase]:
        """
        Simulate an episode and return test cases for main agent and workers.
        """
        print(f"  > Simulating Episode: {episode_id}")
        episode_data = self.df[self.df['episode_id'] == episode_id].sort_values('step_index')
        
        main_user_id = None
        expected_behavior = ""
        self.invoked_workers[episode_id] = []
        
        for _, row in episode_data.iterrows():
            role = row['role']
            original_user_id = row['user_id']
            user_id = self._scope_user_id(original_user_id, episode_id) if pd.notna(original_user_id) else None
            
            if not main_user_id and user_id:
                main_user_id = user_id
            
            if pd.notna(row['expected_behavior']):
                expected_behavior += f"\nStep {row['step_index']}: {row['expected_behavior']}"
            
            if role == 'user':
                await self._simulate_message(row, user_id, episode_id)
            elif role == 'system_time_jump':
                await self._simulate_time_jump(row, episode_id)
        
        # Build test cases
        return self._build_test_cases(episode_id, main_user_id, expected_behavior)
    
    async def _simulate_message(self, row: pd.Series, user_id: str, episode_id: str):
        """Simulate a user message."""
        text = row['input_text']
        is_mpim = str(row['is_mpim']).lower() == 'true'
        slack_ts = row['slack_ts']
        thread_ts = row['thread_ts'] if pd.notna(row['thread_ts']) else None
        author_name = row['author_name']
        author_id = row['author_id']
        
        timestamp = parse(slack_ts)
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=timezone.utc)
        
        # Ensure user exists
        try:
            create_or_update_user(user_id, "TestUser", "testuser", "slack", "T_TEST", "Asia/Kolkata")
        except:
            pass
        
        if is_mpim:
            is_invoked = "@Zarie" in text or "@zarie" in text
            if is_invoked:
                async for _ in self.agent.invoke(
                    user_id=user_id, message=text, medium="End-User via Slack MPIM",
                    timestamp=timestamp, user_timezone="Asia/Kolkata", is_mpim=True,
                    thread_ts=thread_ts, author_name=author_name, author_id=author_id,
                    reply_ts=thread_ts or slack_ts
                ):
                    pass
                self._track_invoked_workers(user_id, episode_id)
            else:
                # Store context without invoking
                user_message = self.agent._create_user_message(
                    text, "End-User via Slack MPIM", timestamp, "Asia/Kolkata", author_name, author_id
                )
                self.agent.state.add_context(
                    user_id, user_message, thread_ts=thread_ts,
                    author_name=author_name, author_id=author_id, slack_ts=slack_ts
                )
        else:
            async for _ in self.agent.invoke(
                user_id=user_id, message=text, medium="End-User via Slack",
                timestamp=timestamp, user_timezone="Asia/Kolkata", is_mpim=False,
                thread_ts=thread_ts, author_name=author_name, author_id=author_id
            ):
                pass
            self._track_invoked_workers(user_id, episode_id)
    
    async def _simulate_time_jump(self, row: pd.Series, episode_id: str):
        """Simulate a time jump and trigger due events."""
        target_time_str = row['slack_ts']
        target_time = parse(target_time_str)
        if target_time.tzinfo is None:
            target_time = target_time.replace(tzinfo=timezone.utc)
        
        print(f"    [Time Jump] -> {target_time}")
        
        from user_manager import get_db_connection
        conn, db_type = get_db_connection()
        cursor = conn.cursor()
        suffix = f"_{episode_id}_{self.run_id}"
        
        try:
            cursor.execute(
                "SELECT * FROM time_events WHERE status = 'ACTIVE' AND user_id LIKE ?",
                (f"%{suffix}",)
            )
            columns = [col[0] for col in cursor.description]
            all_events = [dict(zip(columns, row)) for row in cursor.fetchall()]
            
            print(f"    [Active Events in DB]: {len(all_events)}")
            
            due_events = []
            for ev in all_events:
                trigger = ev['next_trigger_timestamp']
                if isinstance(trigger, str):
                    trigger = parse(trigger)
                if trigger.tzinfo is None:
                    trigger = trigger.replace(tzinfo=timezone.utc)
                
                print(f"    - Event {ev['reminder_name']}: Trigger {trigger} <= Target {target_time}? {trigger <= target_time}")
                
                if trigger <= target_time:
                    structure = {
                        'agent_name': ev['agent_name'],
                        'user_id': ev['user_id'],
                        'reminders': {
                            'recurring': [ev] if ev['is_recurring'] else [],
                            'non_recurring': [ev] if not ev['is_recurring'] else []
                        }
                    }
                    due_events.append(structure)
            
            from run_scheduler import process_event
            for event in due_events:
                await process_event(event, self.worker_agent, self.agent, simulation_timestamp=target_time)
                # Track this worker
                agent_name = event['agent_name']
                user_id = event['user_id']
                if (agent_name, user_id) not in self.invoked_workers[episode_id]:
                    self.invoked_workers[episode_id].append((agent_name, user_id))
        except Exception as e:
            print(f"Error in time jump: {e}")
        finally:
            conn.close()
    
    def _track_invoked_workers(self, user_id: str, episode_id: str):
        """Track workers invoked during agent execution."""
        messages = self.agent.state.get_messages(user_id, exclude_summarised=False) or []
        workers = extract_invoked_workers(messages)
        for agent_name, _ in workers:
            entry = (agent_name, user_id)
            if entry not in self.invoked_workers[episode_id]:
                self.invoked_workers[episode_id].append(entry)
    
    def _build_test_cases(self, episode_id: str, main_user_id: str, 
                          expected_behavior: str) -> list[ConversationalTestCase]:
        """Build test cases for main agent and all invoked workers."""
        test_cases = []
        trace_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "traces")
        
        # 1. Main Agent Test Case
        main_messages = self.agent.state.get_messages(main_user_id, exclude_summarised=False) or []
        main_turns = convert_messages_to_turns(main_messages)
        
        test_cases.append(ConversationalTestCase(
            turns=main_turns,
            expected_outcome=expected_behavior.strip(),
            context=[MAIN_AGENT_CRITERIA],
            additional_metadata={"episode_id": episode_id, "agent_type": "main"}
        ))
        
        # 2. Worker Agent Test Cases
        worker_traces = {}
        for agent_name, scoped_user_id in self.invoked_workers.get(episode_id, []):
            worker_context_json = self.worker_agent.directory.get_context(agent_name, scoped_user_id)
            if worker_context_json:
                worker_messages = json.loads(worker_context_json)
                worker_traces[agent_name] = worker_messages
                worker_turns = convert_messages_to_turns(worker_messages)
                
                test_cases.append(ConversationalTestCase(
                    turns=worker_turns,
                    expected_outcome=f"Worker '{agent_name}' should correctly set time events with proper timezone and message format.",
                    additional_metadata={"episode_id": episode_id, "agent_type": "worker", "agent_name": agent_name}
                ))
        
        # Save trace file
        save_trace(trace_dir, episode_id, self.run_id, expected_behavior, main_messages, worker_traces)
        
        return test_cases


# ============================================================================
# TEST RUNNER
# ============================================================================

@pytest.mark.asyncio
async def test_run_episodes():
    print("\n" + "=" * 50)
    print("STARTING EVALUATION RUN")
    print("=" * 50)
    
    runner = EvalRunner("evals/scenarios/all_episodes.csv")
    episode_ids = runner.df['episode_id'].unique()
    
    # Phase 1: Simulation
    print("\n[PHASE 1] Simulating Episodes...")
    all_test_cases = []
    
    for ep_id in episode_ids:
        test_cases = await runner.simulate_episode(ep_id)
        all_test_cases.extend(test_cases)
    
    print(f"  Generated {len(all_test_cases)} test cases")
    
    # Phase 2: Evaluation
    print("\n[PHASE 2] Running Evaluation...")
    
    # Metrics
    main_agent_geval = ConversationalGEval(
        name="Main Agent Protocol",
        criteria=MAIN_AGENT_CRITERIA,
        evaluation_params=[TurnParams.ROLE, TurnParams.CONTENT, TurnParams.TOOLS_CALLED],
        threshold=0.7
    )
    
    worker_agent_geval = ConversationalGEval(
        name="Worker Agent Protocol", 
        criteria=WORKER_AGENT_CRITERIA,
        evaluation_params=[TurnParams.ROLE, TurnParams.CONTENT, TurnParams.TOOLS_CALLED],
        threshold=0.7
    )
    
    # Note: ToolCorrectnessMetric only works with LLMTestCase, not ConversationalTestCase
    # For ConversationalTestCase, we use ConversationalGEval with tool criteria embedded
    
    # Separate test cases by type
    main_cases = [tc for tc in all_test_cases if tc.additional_metadata.get("agent_type") == "main"]
    worker_cases = [tc for tc in all_test_cases if tc.additional_metadata.get("agent_type") == "worker"]
    
    results_summary = []
    
    # Evaluate Main Agent cases
    if main_cases:
        print(f"  Evaluating {len(main_cases)} main agent test cases...")
        main_results = evaluate(main_cases, [main_agent_geval])
        results_list = main_results.test_results if hasattr(main_results, 'test_results') else main_results
        
        for i, res in enumerate(results_list):
            tc = main_cases[i]
            ep_id = tc.additional_metadata.get("episode_id", "Unknown")
            results_summary.append({
                "episode_id": ep_id,
                "agent_type": "main",
                "status": "PASSED" if res.success else "FAILED",
                "scores": {m.name: m.score for m in res.metrics_data} if res.metrics_data else {},
                "reason": res.metrics_data[0].reason if res.metrics_data else "No reason"
            })
    
    # Evaluate Worker Agent cases (sequentially to avoid rate limits)
    if worker_cases:
        print(f"  Evaluating {len(worker_cases)} worker agent test cases sequentially...")
        for i, tc in enumerate(worker_cases):
            print(f"    [{i+1}/{len(worker_cases)}] Evaluating {tc.additional_metadata.get('agent_name', 'unknown')}...")
            worker_result = evaluate([tc], [worker_agent_geval])
            res = worker_result.test_results[0] if hasattr(worker_result, 'test_results') else worker_result[0]
            
            ep_id = tc.additional_metadata.get("episode_id", "Unknown")
            agent_name = tc.additional_metadata.get("agent_name", "Unknown")
            results_summary.append({
                "episode_id": ep_id,
                "agent_type": "worker",
                "agent_name": agent_name,
                "status": "PASSED" if res.success else "FAILED",
                "scores": {m.name: m.score for m in res.metrics_data} if res.metrics_data else {},
                "reason": res.metrics_data[0].reason if res.metrics_data else "No reason"
            })
    
    # Phase 3: Reporting
    print("\n[PHASE 3] Generating Reports...")
    
    results_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results")
    os.makedirs(results_dir, exist_ok=True)
    
    # Save JSON
    json_path = os.path.join(results_dir, "summary.json")
    with open(json_path, "w") as f:
        json.dump(results_summary, f, indent=2)
    
    # Save TXT with full reasons (wrapped for readability)
    import textwrap
    txt_path = os.path.join(results_dir, "summary.txt")
    with open(txt_path, "w") as f:
        f.write("=" * 80 + "\n")
        f.write("EVALUATION RESULTS SUMMARY\n")
        f.write("=" * 80 + "\n\n")
        
        for r in results_summary:
            agent_suffix = f" ({r.get('agent_name', '')})" if r.get('agent_name') else ""
            f.write(f"Episode: {r['episode_id']}\n")
            f.write(f"Type: {r['agent_type']}{agent_suffix}\n")
            f.write(f"Status: {r['status']}\n")
            f.write(f"Scores: {r.get('scores', {})}\n")
            # Wrap reason text at 80 chars for readability
            reason = r.get('reason', 'No reason')
            wrapped_reason = textwrap.fill(reason, width=80)
            f.write(f"Reason:\n{wrapped_reason}\n")
            f.write("\n" + "-" * 80 + "\n\n")
    
    # Print summary
    print("\n" + "-" * 80)
    print(f"{'EPISODE':<20} | {'TYPE':<8} | {'STATUS':<8} | SCORES")
    print("-" * 80)
    
    for r in results_summary:
        scores_str = ", ".join(f"{k}: {v:.2f}" for k, v in r.get("scores", {}).items())
        agent_suffix = f" ({r.get('agent_name', '')})" if r.get('agent_name') else ""
        print(f"{r['episode_id']:<20} | {r['agent_type']:<8}{agent_suffix} | {r['status']:<8} | {scores_str}")
    
    print("-" * 80)
    print(f"\nResults saved to:\n - {json_path}\n - {txt_path}")
    print("=" * 50 + "\n")


if __name__ == "__main__":
    asyncio.run(test_run_episodes())
