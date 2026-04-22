from Ion import PentestAgent, ObservabilityLogger


def main():
    logger = ObservabilityLogger("./logs")
    agent = PentestAgent(logger=logger, agent_mode="ctf")
    query = "对目标 119.45.211.148:80 进行渗透，找到FLAG值"
    result = agent.run(query)
    print(result)
    print(f"\n[Usage: {agent.get_usage_summary()}]")
    agent.save_tasks("attack_plan.json")


if __name__ == "__main__":
    main()
