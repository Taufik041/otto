# scripts/test_orchestrator.py
from k8s_script import create_sandbox, destroy_sandbox
# name = create_sandbox("s1", "https://github.com/Taufik041/otto_test")
# print("created", name)
# now: kubectl get jobs  -> otto-s1 running
#      kubectl logs job/otto-s1 -> "Listening for actions"
#      poke it, or run the agent
# then: 
destroy_sandbox("s1")