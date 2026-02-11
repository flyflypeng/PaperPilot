"""
API test utilities for testing LLM and MinerU connections
"""

import requests


def test_llm_api(model: str, base_url: str, api_key: str) -> tuple[bool, str]:
    """
    Test LLM API connection

    Args:
        model: Model name
        base_url: Base URL
        api_key: API key

    Returns:
        (success, error_message)
    """
    try:
        from openai import OpenAI

        client = OpenAI(api_key=api_key, base_url=base_url)

        # Try to list models
        models = client.models.list()
        if not models.data:
            return False, "No models available"

        # Try a simple completion
        response = client.chat.completions.create(
            model=model, messages=[{"role": "user", "content": "Hi"}], max_tokens=10
        )

        if response.choices and response.choices[0].message:
            return True, "Connection successful"
        else:
            return False, "No valid response"

    except Exception as e:
        return False, str(e)


def test_mineru_api(server_url: str) -> tuple[bool, str]:
    """
    Test MinerU local server connection

    Args:
        server_url: MinerU server URL

    Returns:
        (success, error_message)
    """
    try:
        # Test health endpoint
        test_url = f"{server_url.rstrip('/')}/health"
        response = requests.get(test_url, timeout=10)

        if response.status_code == 200:
            return True, "MinerU server is accessible"
        else:
            return False, f"Server returned status {response.status_code}"

    except requests.exceptions.ConnectionError:
        return False, f"Cannot connect to {server_url}"
    except requests.exceptions.Timeout:
        return False, "Connection timeout"
    except Exception as e:
        return False, str(e)


def test_mineru_api_token(api_token: str) -> tuple[bool, str]:
    """
    Test MinerU API token validity

    Args:
        api_token: MinerU API token

    Returns:
        (success, error_message)
    """
    try:
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_token}",
        }

        # Try a simple API call (request upload links with a dummy file)
        # Using a dummy file name to test token validity without actually uploading
        response = requests.post(
            "https://mineru.net/api/v4/file-urls/batch",
            headers=headers,
            json={
                "files": [{"name": "test.pdf", "data_id": "test"}],
                "model_version": "vlm",
            },
            timeout=10,
        )

        if response.status_code == 200:
            result = response.json()
            if result.get("code") == 0:
                return True, "API token is valid"
            else:
                # If we get a business logic error, it means the token is valid
                # but the request parameters might be wrong (e.g., file doesn't exist)
                # This is still a success for token validation purposes
                error_msg = result.get("msg", "Unknown error")
                return True, f"API token is valid (Note: {error_msg})"
        elif response.status_code == 401:
            return False, "Invalid API token or authentication failed"
        elif response.status_code == 403:
            return False, "Access forbidden - check your token permissions"
        else:
            return False, f"HTTP {response.status_code}: {response.text}"

    except requests.exceptions.ConnectionError:
        return False, "Cannot connect to MinerU API server"
    except requests.exceptions.Timeout:
        return False, "Connection timeout"
    except Exception as e:
        return False, f"Connection failed: {str(e)}"
