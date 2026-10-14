import os

# Spec 05: an app started with its lifespan (test_events.py) must not schedule the
# Skiller's background scouting of GitHub. The Node launchers do the same (demoEnv).
os.environ["AGENT_WORLD_SKILLER"] = "0"
