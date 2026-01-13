"""
Runs:

docker compose build --no-cache api
docker compose down -v
docker compose up -d
docker compose run --rm api python -m alembic upgrade head
"""
import subprocess as sp


def restart_and_upgrade_head():
    commands = [
        'docker compose build --no-cache api',
        'docker compose down -v',
        'docker compose up -d',
        'docker compose run --rm api python -m alembic upgrade head'
    ]
    for command in commands:
        try:
            stdout, stderr = sp.Popen(
                command,
                stdout=sp.PIPE,
                stderr=sp.PIPE
            ).communicate()
            print(f'[success] Executed: Command: {command} - stdout: {stdout.decode()} - stderr: {stderr.decode()}')
        except IOError as io_error:
            print(f'[error] xecuted: Command: {command} - error: {io_error}')


if __name__ == '__main__':
    restart_and_upgrade_head()