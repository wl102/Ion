import argparse
import sys

from Ion.agent import PentestAgent


def main():
    parser = argparse.ArgumentParser(
        description="Ion - Cybersecurity Penetration Testing Agent"
    )
    parser.add_argument("query", nargs="?", help="The task or query for the agent")
    parser.add_argument(
        "--task-file", help="Load a predefined task graph from JSON file"
    )
    parser.add_argument("--log-dir", help="Directory for observability logs")
    parser.add_argument("--model", help="Override MODEL_ID")
    parser.add_argument("--base-url", help="Override OPENAI_BASE_URL")
    parser.add_argument("--api-key", help="Override OPENAI_API_KEY")
    parser.add_argument(
        "--system-prompt", help="Custom system prompt (legacy mode only)"
    )
    parser.add_argument(
        "--agent-mode",
        default="default",
        choices=["default", "ctf", "pentest", "aggressive", "stealthy"],
        help="Dynamic prompt mode for Layer 2 templates (default: default)",
    )
    parser.add_argument(
        "--no-layered-prompts",
        action="store_true",
        help="Disable layered prompts and use the legacy hard-coded system prompt",
    )
    parser.add_argument(
        "-i", "--interactive", action="store_true", help="Interactive mode"
    )
    parser.add_argument(
        "--max-turns", type=int, help="Override AGENT_MAX_LOOP (0 = unlimited)"
    )
    parser.add_argument(
        "--context-max-tokens",
        type=int,
        help="Override CONTEXT_MAX_TOKENS (0 = disabled)",
    )

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
        import os
        from Ion.observability import ObservabilityLogger

        os.environ.setdefault("ION_LOG_DIR", args.log_dir)
        kwargs["logger"] = ObservabilityLogger(log_dir=args.log_dir)

    # Layered prompt configuration
    kwargs["use_layered_prompts"] = not args.no_layered_prompts
    kwargs["agent_mode"] = args.agent_mode

    agent = PentestAgent(**kwargs)

    if args.max_turns is not None:
        kwargs["max_turns"] = args.max_turns
    if args.context_max_tokens is not None:
        kwargs["context_max_tokens"] = args.context_max_tokens

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
