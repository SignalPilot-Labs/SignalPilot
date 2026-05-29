"""Entry point for knowledge base generation.

Usage:
    python -m benchmark.run_kb <instance_id> [--model claude-sonnet-4-6]
"""
from benchmark.runners.kb_generator import main

if __name__ == "__main__":
    main()
