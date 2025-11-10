import asyncio
import csv
from agent.agent import Agent

csv_file = 'evals/eval.csv'
user_id = 'eval_user'

with open(csv_file, 'r') as f:
    reader = csv.reader(f)
    rows = list(reader)

    # Create a single event loop for all iterations
    async def run_all_evals():
        for idx, row in enumerate(rows[1:], 1):  # Skip header row
            if row:  # Check if row is not empty
                message = row[0]
                
                print(f"\n[{idx}/{len(rows)-1}] Processing evaluation...")
                print(f"Input: {message}")
                
                agent = Agent()
                print("Invoking agent...")
                response = await agent.invoke(user_id, message, "EVAL")
                print(f"Response: {response['content']}")
                print("-" * 50)
    
    asyncio.run(run_all_evals())

print("\nEvaluation complete!")