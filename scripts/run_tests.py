#!/usr/bin/env python3
"""
Test Runner Script for Astro Account Manager.
Runs the complete pytest suite and outputs results.
"""

import os
import subprocess
import sys

def main() -> None:
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    os.chdir(project_root)
    
    print("[TEST] Running Astro Account Manager Test Suite (149 tests)...")
    cmd = [sys.executable, "-m", "pytest", "-v"]
    result = subprocess.run(cmd)
    sys.exit(result.returncode)

if __name__ == "__main__":
    main()
