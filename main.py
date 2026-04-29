import os

from Ion import IonAgent, ObservabilityLogger


def main():
    os.environ.setdefault("ION_LOG_DIR", "./logs_0429")
    logger = ObservabilityLogger("./logs_0429_01")
    agent = IonAgent(logger=logger, mode="ctf")
    query = "对目标 119.45.211.148:80 进行渗透，找到FLAG值"
    result = agent.run(query)
    print(result)
    print(f"\n[Usage: {agent.get_usage_summary()}]")
    agent.save_tasks("logs/attack_plan_01.json")


if __name__ == "__main__":
    main()
