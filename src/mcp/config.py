import logging
import os

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - fallback when dependency not installed

    def load_dotenv():
        logging.getLogger(__name__).warning(
            "python-dotenv not installed; skipping .env load"
        )


load_dotenv()  # Load environment variables from .env file

OBSIDIAN_VAULT_PATH = os.getenv(
    "OBSIDIAN_VAULT_PATH", "/Users/prinstonpalmer/Library/Mobile Documents/iCloud~md~obsidian/Documents/Test"
)

# Define specific subfolders within your vault for agent interaction

AGENT_INPUT_DIR = "Agent Inputs"  # Where agents look for new tasks/instructions
AGENT_OUTPUT_DIR = "Agent Outputs"  # Where agents write their reports/results

# You can add more configuration here, e.g., agent specific settings, API keys etc.
