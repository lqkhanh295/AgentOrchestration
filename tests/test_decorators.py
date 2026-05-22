import pytest
from src.sdk.decorators import task

def test_task_decorator_retries_validation():
    with pytest.raises(ValueError, match="between 0 and 10"):
        @task(retries=-1)
        def dummy_task_negative():
            pass

    with pytest.raises(ValueError, match="between 0 and 10"):
        @task(retries=15)
        def dummy_task_high():
            pass

    with pytest.raises(ValueError, match="between 0 and 10"):
        @task(retries="5")
        def dummy_task_string():
            pass

    @task(retries=3)
    def dummy_task_valid():
        pass
    
    assert dummy_task_valid.__task_config__["retries"] == 3
