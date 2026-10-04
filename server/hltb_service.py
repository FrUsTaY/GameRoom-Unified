import os
import requests
import logging
from typing import Optional

logger = logging.getLogger(__name__)

HLTB_SERVICE_URL = os.environ.get("HLTB_SERVICE_URL", "http://localhost:3000")

def get_hltb_playtime(title: str) -> Optional[float]:
    """
    Fetches game playtime from the HLTB Node microservice.
    Prioritizes mainExtra, fallback to main.
    Returns playtime in hours, or None if not found or on error.
    """
    if not title:
        return None

    try:
        url = f"{HLTB_SERVICE_URL}/search"
        params = {"title": title}
        # 10 second timeout as requested
        response = requests.get(url, params=params, timeout=10)

        if response.status_code != 200:
            logger.warning(f"HLTB service returned {response.status_code} for title '{title}'")
            return None

        data = response.json()
        main_extra = data.get("mainExtra")
        main = data.get("main")

        if main_extra is not None and float(main_extra) > 0:
            return round(float(main_extra), 1)
        if main is not None and float(main) > 0:
            return round(float(main), 1)

        return None
    except requests.Timeout:
        logger.warning(f"Timeout connecting to HLTB service for title '{title}'")
        return None
    except requests.RequestException as e:
        logger.error(f"Error connecting to HLTB service for title '{title}': {e}")
        return None
    except Exception as e:
        logger.error(f"Unexpected error getting HLTB playtime for title '{title}': {e}")
        return None
