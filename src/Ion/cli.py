import argparse
import sys

from Ion.agent import PentestAgent
from Ion.tasks import TaskManager


def main():
    parser = argparse.ArgumentParser(description="Ion - Cybersecurity Penetration Testing Agent")
    parser.add_argument("query", nargs="?", help="The task or query for the agent")
    parser.add_argument("--task-file", help="Load a predefined task graph from JSON file")
    parser.add_argument("--log-dir", help="Directory for observability logs")
    parser.add_argument("--model", help="Override MODEL_ID")
    parser.add_argument("--base-url", help="Override OPENAI_BASE_URL")
    parser.add_argument("--api-key", help="Override OPENAI_API_KEY")
    parser.add_argument("--system-prompt", help="Custom system prompt")
    parser.add_argument("-i", "--interactive", action="store_true", help="Interactive mode")

    args = parser.parse_args()

    if not args.query and not args.interactive:
        parser.print_help()
        sys.exit(1)

    kwargs = {}
    if args.model:
        kwargs["model_id"] = args.model
    if args.base_url:
        kwargs["base_url"] = args.base_url
    if args.api_key:
        kwargs["api_key"] = args.api_key
    if args.system_prompt:
        kwargs["system_prompt"] = args.system_prompt
    if args.log_dir:
        from Ion.observability import ObservabilityLogger
        kwargs["logger"] = ObservabilityLogger(log_dir=args.log_dir)

    agent = PentestAgent(**kwargs)

    if args.task_file:
        agent.load_tasks(args.task_file)

    if args.interactive:
        print("Ion Pentest Agent - Interactive Mode")
        print("Type 'exit' or 'quit' to leave.\n")
        while True:
            try:
                query = input("Ion> ")
            except (EOFError, KeyboardInterrupt):
                print()
                break
            query = query.strip()
            if query.lower() in ("exit", "quit"):
                break
            if not query:
                continue
            result = agent.run(query)
            print(result)
            print()
    else:
        result = agent.run(args.query)
        print(result)
        usage = agent.get_usage_summary()
        if usage["total_tokens"]:
            print(f"\n[Tokens: {usage['total_tokens']}]")


if __name__ == "__main__":
    main()
