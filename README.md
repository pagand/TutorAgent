Run the server with 
```
uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload

```


Run all tests: pytest
Run only Stage 3 tests: pytest -m stage3
Run only Stage 1 and Stage 2 tests: pytest -m "stage1 or stage2"
Run all tests except real LLM calls: pytest -m "not llm_integration"
Run only real LLM integration tests: pytest -m llm_integration 


default test:
pytest tests/test_llm_switching.py -m "not llm_integration"
or
pytest tests/test_llm_switching.py -k test_hint_uses_mock_by_default


integration test (real LLM):
pytest tests/test_llm_switching.py -m llm_integration -s
