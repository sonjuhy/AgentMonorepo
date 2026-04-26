# agents/orchestra_agent/tests/test_llm_key_management.py

from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock, AsyncMock
import pytest
from fastapi import FastAPI, Depends, HTTPException
from pydantic import BaseModel, Field
from typing import Dict, Any, List

# --- Mocking and Test Setup ---

# Mock StateManager and its methods
class MockStateManager:
    def __init__(self):
        # Let's just use a plain dict for profiles
        self.users_db: Dict[str, Dict[str, Any]] = {} 

    async def get_user_profile(self, user_id: str) -> Dict[str, Any] | None:
        return self.users_db.get(user_id)

    async def update_user_profile(self, user_id: str, updates: Dict[str, Any]) -> Dict[str, Any] | None:
        user = await self.get_user_profile(user_id)
        if user:
            for key, value in updates.items():
                user[key] = value
            self.users_db[user_id] = user
            return user
        return None

# Instantiate the mock state manager for tests
test_state_manager_instance = MockStateManager()
# Seed with some initial data for testing
test_state_manager_instance.users_db["test_user_123"] = {
    "user_id": "test_user_123",
    "name": "testuser",
    "llm_keys": {"gemini": "old-gemini-key"} # Pre-existing key
}

# Mock authentication dependency callables
async def mock_verify_client_key_success():
    """Simulates successful authentication."""
    return None

async def mock_verify_client_key_unauthenticated():
    """Simulates unauthenticated access."""
    raise HTTPException(status_code=403, detail="클라이언트 권한 인증에 실패했습니다. (유효하지 않은 X-API-Key)")

# --- Minimal FastAPI App for Testing ---
test_app = FastAPI()

class LLMKeyUpdateBody(BaseModel):
    api_key: str = Field(..., description="LLM 제공업체의 API 키.")

SUPPORTED_LLM_PROVIDERS = ["gemini", "claude", "openai", "local"]

# We mock ctx since the main app uses ctx.state_manager
class MockCtx:
    state_manager = test_state_manager_instance

mock_ctx = MockCtx()

# --- API Endpoint Definition ---
@test_app.put("/users/{user_id}/llm_keys/{provider_name}", tags=["사용자"],
         dependencies=[Depends(mock_verify_client_key_success)])
async def update_llm_api_key(
    user_id: str,
    provider_name: str,
    body: LLMKeyUpdateBody
) -> dict[str, Any]:
    """사용자의 특정 LLM 제공업체 API 키를 설정하거나 업데이트합니다."""
    if provider_name not in SUPPORTED_LLM_PROVIDERS:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid LLM provider '{provider_name}'. Supported providers are: {', '.join(SUPPORTED_LLM_PROVIDERS)}"
        )

    if not body.api_key or not body.api_key.strip():
        raise HTTPException(status_code=400, detail="API key must be a non-empty string.")

    profile = await mock_ctx.state_manager.get_user_profile(user_id)
    if not profile:
        raise HTTPException(status_code=404, detail="User profile not found.")

    current_keys = profile.get("llm_keys") or {}
    current_keys[provider_name] = body.api_key

    await mock_ctx.state_manager.update_user_profile(user_id, {"llm_keys": current_keys})

    return {"message": "LLM API key updated successfully."}


@test_app.get("/users/{user_id}/profile", tags=["사용자"],
         dependencies=[Depends(mock_verify_client_key_success)])
async def get_profile(user_id: str) -> dict[str, Any]:
    profile = await mock_ctx.state_manager.get_user_profile(user_id)
    if not profile:
        raise HTTPException(status_code=404, detail="User profile not found.")
    # Return a copy to avoid mutating the db in the mock
    profile_copy = dict(profile)
    profile_copy.pop("llm_keys", None)
    return profile_copy


# --- Fixture for TestClient ---
@pytest.fixture(scope="module")
def client():
    """Provides a TestClient instance for the FastAPI app."""
    with TestClient(test_app) as c:
        yield c


# --- Test Cases ---

def test_update_llm_api_key_success(client: TestClient):
    """
    Tests that a user can successfully update their LLM API key for a specific provider.
    """
    user_id = "test_user_123"
    provider = "gemini"
    api_key_to_set = "sk-test-gemini-key-12345"
    request_data = {"api_key": api_key_to_set}
    
    response = client.put(f"/users/{user_id}/llm_keys/{provider}", json=request_data)
    assert response.status_code == 200
    assert response.json() == {"message": "LLM API key updated successfully."}

    # Verify the key was updated
    assert test_state_manager_instance.users_db[user_id]["llm_keys"].get(provider) == api_key_to_set


def test_update_llm_api_key_invalid_provider(client: TestClient):
    """
    Tests that updating an LLM API key with an invalid provider name returns a 400 error.
    """
    user_id = "test_user_123"
    provider = "invalid_llm_provider"
    api_key_to_set = "sk-some-key"
    request_data = {"api_key": api_key_to_set}

    response = client.put(f"/users/{user_id}/llm_keys/{provider}", json=request_data)

    assert response.status_code == 400
    assert "detail" in response.json()
    assert "Invalid LLM provider" in response.json()["detail"]


def test_update_llm_api_key_missing_key(client: TestClient):
    """
    Tests that submitting a request without an API key returns a 422 validation error.
    """
    user_id = "test_user_123"
    provider = "gemini"
    request_data = {} # Missing "api_key" field

    response = client.put(f"/users/{user_id}/llm_keys/{provider}", json=request_data)

    assert response.status_code == 422 
    error_details = response.json()["detail"]
    assert isinstance(error_details, list)

    found_required_field_error = False
    for error in error_details:
        if error.get("type") == "missing" and "api_key" in error.get("loc", []):
            found_required_field_error = True
            break
    assert found_required_field_error, "Expected missing field error for api_key."


def test_update_llm_api_key_unauthorized():
    """
    Tests that an unauthenticated user cannot update LLM API keys.
    """
    user_id = "test_user_123"
    provider = "gemini"
    api_key_to_set = "sk-some-key"
    request_data = {"api_key": api_key_to_set}

    with TestClient(test_app) as unauthorized_client:
        auth_dependency_callable_to_override = mock_verify_client_key_success 
        unauthorized_client.app.dependency_overrides[auth_dependency_callable_to_override] = mock_verify_client_key_unauthenticated
        
        response = unauthorized_client.put(f"/users/{user_id}/llm_keys/{provider}", json=request_data)
        assert response.status_code == 403 # HTTP 403 Forbidden for verify_client_key failure
        assert "인증에 실패했습니다" in response.json()["detail"]


def test_llm_keys_not_returned_in_profile(client: TestClient):
    """
    Tests that sensitive LLM API keys are excluded from the default user profile response.
    """
    user_id = "test_user_123"
    provider = "gemini"
    api_key_to_set = "sk-secure-gemini-key"
    
    auth_dependency_callable_to_override = mock_verify_client_key_success
    original_override = test_app.dependency_overrides.get(auth_dependency_callable_to_override)
    test_app.dependency_overrides[auth_dependency_callable_to_override] = mock_verify_client_key_success
    
    try:
        response_update = client.put(f"/users/{user_id}/llm_keys/{provider}", json={"api_key": api_key_to_set})
        assert response_update.status_code == 200

        response_get_profile = client.get(f"/users/{user_id}/profile")
        assert response_get_profile.status_code == 200
        profile_data = response_get_profile.json()

        assert "llm_keys" not in profile_data
        assert "user_id" in profile_data
    finally:
        if original_override is not None:
            test_app.dependency_overrides[auth_dependency_callable_to_override] = original_override
        else:
            test_app.dependency_overrides.pop(auth_dependency_callable_to_override, None)
