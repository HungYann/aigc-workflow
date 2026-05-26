# Tests for AIGC Workflow

Run all tests:

```bash
cd /Users/liuhongyang/Desktop/content/aigc-workflow
python3 -m unittest discover -s tests -p 'test_*.py' -v
```

Covered scenarios:

1. Multi-user concurrent submit + quota reject.
2. Success path with final result URL.
3. Failure path + quota refund compensation.
4. Retry logic on script step.
5. SSE-like progress stream final event.
6. Dedup cache hit reduces repeated video generation.
7. Loop detection guard in ReAct flow.
8. Tool schema contract.
9. Default latency contract (script 5s, video 30s).
10. Repository and account service unit tests.
