"""
Runs docker compose up on the required containers 
"""
import sys
from typing import List, Optional
from utils import run_commands


def restart_container_services(services : Optional[List[str]] = None) -> bool:
    """
    Runs docker compose up on the container_names outlined in docker-compose.yml
    """
    commands = []
    if services is None:
        commands.extend([
            'docker compose --profile cpu down',
            'docker compose --profile cpu up -d',
            'docker compose logs -f --tail=50 llm'
        ])
    else:
        services = ' '.join(services)
        commands.extend([
            f'docker compose --profile cpu down {services}',
            f'docker compose --profile cpu up -d {services}',
            f'docker compose logs -f --tail=200'
        ])
    return run_commands(commands)


if __name__ == "__main__":
    services_to_restart = None
    return_code = 0 if restart_container_services(services=services_to_restart) else 1
    sys.exit(return_code)

