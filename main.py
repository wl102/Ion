from Ion import PentestAgent


def main():
    agent = PentestAgent()
    query = "对目标example.com 进行渗透测试"
    result = agent.run(query)
    print(result)
    print(f"\n[Usage: {agent.get_usage_summary()}]")
    agent.save_tasks("attack_plan.json")


if __name__ == "__main__":
    main()
