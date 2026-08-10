#!/usr/bin/env python3
"""
Development Launcher for Astro Account Manager.
Launches the application directly from source code.
"""

import os
import sys

def main() -> None:
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    os.chdir(project_root)
    sys.path.insert(0, project_root)
    
    print("[DEV] Starting Astro Account Manager (Development Mode)...")
    print(f"[DEV] Project Root: {project_root}")
    
    from main import main as app_main
    app_main()

if __name__ == "__main__":
    main()
