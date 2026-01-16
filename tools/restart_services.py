"""
Runs docker compose up on the required containers 
"""
import sys
from typing import List, Optional
from utils import run_commands


def restart_container_services() -> bool:
    """
    Runs docker compose up on the container_names outlined in docker-compose.yml
    """
    commands = [
        'docker compose --profile cpu down',
        'docker compose --profile cpu build --no-cache',
        'docker compose --profile cpu up -d',
        # 'docker compose logs -f --tail=50 llm'
    ]
    return run_commands(commands)


if __name__ == "__main__":
    return_code = 0 if restart_container_services() else 1
    sys.exit(return_code)

