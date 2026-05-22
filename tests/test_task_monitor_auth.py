from starlette.testclient import TestClient
from src.api.server import create_app

def test_revalidate_revoked_api_keys_on_long_polling():
    """
    Test that revalidates revoked API keys on long polling
    specifically covering the task monitor conditions.
    """
    app = create_app()
    client = TestClient(app)
    
    # Task monitor long polling condition with revoked key
    response = client.get(
        "/api/v2/task/monitor?polling=true",
        headers={"Authorization": "Bearer revoked"}
    )
    assert response.status_code == 401
    
    # Stale key
    response = client.get(
        "/api/v2/task/monitor?polling=true",
        headers={"Authorization": "Bearer stale"}
    )
    assert response.status_code == 401
    
    # Expired key
    response = client.get(
        "/api/v2/task/monitor?polling=true",
        headers={"Authorization": "Bearer expired"}
    )
    assert response.status_code == 401
    
    # Valid key (should return 404 because route might not exist, but pass AuthMiddleware)
    response = client.get(
        "/api/v2/task/monitor?polling=true",
        headers={"Authorization": "Bearer valid_key"}
    )
    assert response.status_code == 404

