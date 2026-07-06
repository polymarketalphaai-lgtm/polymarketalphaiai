import os
import json

# Define the base path
BASE_PATH = "/mnt/agents/output/polymarket_alpha_ai"
os.makedirs(BASE_PATH, exist_ok=True)

# Phase 1: Create Directory Structure
dirs = [
    "last30days/core",
    "last30days/collectors/news",
    "last30days/collectors/openbb",
    "last30days/collectors/social/twitter",
    "last30days/collectors/social/truthsocial",
    "last30days/collectors/social/reddit",
    "last30days/collectors/social/telegram",
    "last30days/collectors/social/discord",
    "last30days/collectors/polysee",
    "last30days/collectors/polymarket",
    "last30days/collectors/macro",
    "last30days/collectors/crypto",
    "last30days/enrichment/sentiment",
    "last30days/enrichment/entity_extraction",
    "last30days/enrichment/embeddings",
    "last30days/enrichment/summarization",
    "last30days/correlation",
    "last30days/reports",
    "last30days/database",
    "last30days/scheduler",
    "last30days/api",
    "last30days/config",
    "last30days/utils",
    "last30days/tests/unit",
    "last30days/tests/integration",
    "last30days/tests/performance",
    "last30days/logs",
    "last30days/data/raw",
    "last30days/data/processed",
]

for d in dirs:
    os.makedirs(os.path.join(BASE_PATH, d), exist_ok=True)

print("✅ Directory structure created")