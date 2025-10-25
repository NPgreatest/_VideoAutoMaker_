from __future__ import annotations
from pathlib import Path
from typing import Any, Dict, Optional
import requests
import time
import random

from .constants import (
    SILICONFLOW_API_TOKEN, TEXT_TO_VIDEO_MODEL,
    SILICONFLOW_SUBMIT_URL, SILICONFLOW_STATUS_URL,
    DEFAULT_HEADERS, REQUEST_TIMEOUT, IMAGE_SIZE
)

def submit_video(prompt: str, max_retries: int = 3, base_delay: float = 1.0) -> Optional[str]:
    if not SILICONFLOW_API_TOKEN:
        return None
    
    for attempt in range(max_retries):
        try:
            r = requests.post(
                SILICONFLOW_SUBMIT_URL,
                headers=DEFAULT_HEADERS,
                json={"model": TEXT_TO_VIDEO_MODEL, "prompt": prompt, "image_size" : IMAGE_SIZE},
                timeout=REQUEST_TIMEOUT,
            )
            
            # Check HTTP status code
            if r.status_code != 200:
                raise requests.exceptions.RequestException(f"HTTP {r.status_code}: {r.text}")
            
            # Parse response
            response_data = r.json()
            request_id = response_data.get("requestId")
            
            # Check if we got a valid request ID
            if not request_id:
                raise ValueError(f"No requestId in response: {response_data}")
            
            # Check if the response indicates failure
            status = response_data.get("status", "").lower()
            if status == "failed" or status == "error":
                raise ValueError(f"API returned failure status: {response_data}")
            
            print(f"✅ Video submission successful, requestId: {request_id}")
            return request_id
            
        except (requests.exceptions.RequestException, ValueError, KeyError) as e:
            if attempt == max_retries - 1:
                print(f'❌ Submit video failed after {max_retries} attempts: {e}')
                return None
            
            # Exponential backoff with jitter
            delay = base_delay * (2 ** attempt) + random.uniform(0, 1)
            print(f'⚠️  Submit video attempt {attempt + 1} failed: {e}, retrying in {delay:.2f}s...')
            time.sleep(delay)
        except Exception as e:
            print(f'❌ Submit video failed with unexpected error: {e}')
            return None
    
    return None

def check_status(request_id: str) -> Dict[str, Any]:
    if not SILICONFLOW_API_TOKEN:
        return {"status": "Error", "error": "Missing API token"}
    try:
        r = requests.post(
            SILICONFLOW_STATUS_URL,
            headers=DEFAULT_HEADERS,
            json={"requestId": request_id},
            timeout=REQUEST_TIMEOUT,
        )
        
        # Check HTTP status code
        if r.status_code != 200:
            return {"status": "Error", "error": f"HTTP {r.status_code}: {r.text}"}
        
        response_data = r.json()
        return response_data
        
    except requests.exceptions.RequestException as e:
        return {"status": "Error", "error": f"Request failed: {str(e)}"}
    except Exception as e:
        return {"status": "Error", "error": f"Unexpected error: {str(e)}"}

def download_to(url: str, target_path: Path) -> None:
    target_path.parent.mkdir(parents=True, exist_ok=True)
    with requests.get(url, stream=True, timeout=REQUEST_TIMEOUT) as r:
        r.raise_for_status()
        with open(target_path, "wb") as f:
            for chunk in r.iter_content(chunk_size=1024 * 512):
                if chunk: f.write(chunk)
