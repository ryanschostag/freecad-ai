"""
Utility for running shell commands
"""
import os
from typing import List


def run_commands(commands : List[str]) -> bool:
    """
    - Runs the given list of commands through a subprocess
    - Outputs the results on the terminal
    - Returns True when there no errors, else False
    """    
    for command in commands:
        try:
            os.system(command)
            print(f'[success] Executed command: {command}')
        except Exception as _error:
            print(f'[error] Executed command: {command}\n  error: {_error}')
