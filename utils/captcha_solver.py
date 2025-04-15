import os
import asyncio
import aiohttp
import base64
from typing import Dict, Any, Optional

from utils.logger import get_logger

logger = get_logger(__name__)


class CaptchaSolver:
    """Handles CAPTCHA solving through external services."""

    def __init__(self, config: Dict[str, Any]):
        """
        Initialize CAPTCHA solver.

        Args:
            config: CAPTCHA solver configuration
        """
        self.config = config
        self.service = config.get("service", "none")
        self.api_key = config.get("api_key", "")

    async def solve(self, image_path: str) -> Optional[str]:
        """
        Solve a CAPTCHA.

        Args:
            image_path: Path to CAPTCHA image

        Returns:
            CAPTCHA solution or None if failed
        """
        if self.service == "none" or not self.api_key:
            logger.warning("CAPTCHA solving service not configured")
            return None

        logger.info(f"Solving CAPTCHA using {self.service} service")

        if self.service == "2captcha":
            return await self._solve_with_2captcha(image_path)
        elif self.service == "anticaptcha":
            return await self._solve_with_anticaptcha(image_path)
        else:
            logger.error(f"Unsupported CAPTCHA service: {self.service}")
            return None

    async def _solve_with_2captcha(self, image_path: str) -> Optional[str]:
        """
        Solve CAPTCHA using 2captcha service.

        Args:
            image_path: Path to CAPTCHA image

        Returns:
            CAPTCHA solution or None if failed
        """
        try:
            # Check if image exists
            if not os.path.exists(image_path):
                logger.error(f"CAPTCHA image not found: {image_path}")
                return None

            # Read image file
            with open(image_path, "rb") as f:
                image_data = f.read()

            # Encode image as base64
            image_base64 = base64.b64encode(image_data).decode("utf-8")

            # Submit CAPTCHA
            async with aiohttp.ClientSession() as session:
                # Step 1: Submit the CAPTCHA
                params = {
                    "key": self.api_key,
                    "method": "base64",
                    "body": image_base64,
                    "json": 1
                }

                async with session.post("https://2captcha.com/in.php", data=params) as response:
                    response_data = await response.json()

                    if response_data.get("status") != 1:
                        logger.error(f"Error submitting CAPTCHA: {response_data.get('request')}")
                        return None

                    captcha_id = response_data.get("request")

                # Step 2: Wait for the result
                for _ in range(30):  # Try for 30 * 5 seconds = 2.5 minutes
                    await asyncio.sleep(5)

                    params = {
                        "key": self.api_key,
                        "action": "get",
                        "id": captcha_id,
                        "json": 1
                    }

                    async with session.get("https://2captcha.com/res.php", params=params) as response:
                        response_data = await response.json()

                        if response_data.get("status") == 1:
                            captcha_solution = response_data.get("request")
                            logger.info("CAPTCHA solved successfully")
                            return captcha_solution

                        if response_data.get("request") != "CAPCHA_NOT_READY":
                            logger.error(f"Error getting CAPTCHA solution: {response_data.get('request')}")
                            return None

                logger.error("Timeout waiting for CAPTCHA solution")
                return None

        except Exception as e:
            logger.error(f"Error solving CAPTCHA with 2captcha: {str(e)}")
            return None

    async def _solve_with_anticaptcha(self, image_path: str) -> Optional[str]:
        """
        Solve CAPTCHA using Anti Captcha service.

        Args:
            image_path: Path to CAPTCHA image

        Returns:
            CAPTCHA solution or None if failed
        """
        try:
            # Check if image exists
            if not os.path.exists(image_path):
                logger.error(f"CAPTCHA image not found: {image_path}")
                return None

            # Read image file
            with open(image_path, "rb") as f:
                image_data = f.read()

            # Encode image as base64
            image_base64 = base64.b64encode(image_data).decode("utf-8")

            # Submit CAPTCHA
            async with aiohttp.ClientSession() as session:
                # Step 1: Create task
                task_data = {
                    "clientKey": self.api_key,
                    "task": {
                        "type": "ImageToTextTask",
                        "body": image_base64,
                        "phrase": False,
                        "case": False,
                        "numeric": 0,
                        "math": False,
                        "minLength": 0,
                        "maxLength": 0
                    }
                }

                async with session.post("https://api.anti-captcha.com/createTask", json=task_data) as response:
                    response_data = await response.json()

                    if response_data.get("errorId") != 0:
                        logger.error(f"Error creating CAPTCHA task: {response_data.get('errorDescription')}")
                        return None

                    task_id = response_data.get("taskId")

                # Step 2: Get task result
                for _ in range(30):  # Try for 30 * 5 seconds = 2.5 minutes
                    await asyncio.sleep(5)

                    result_data = {
                        "clientKey": self.api_key,
                        "taskId": task_id
                    }

                    async with session.post("https://api.anti-captcha.com/getTaskResult", json=result_data) as response:
                        response_data = await response.json()

                        if response_data.get("errorId") != 0:
                            logger.error(f"Error getting CAPTCHA result: {response_data.get('errorDescription')}")
                            return None

                        if response_data.get("status") == "ready":
                            captcha_solution = response_data.get("solution", {}).get("text")
                            logger.info("CAPTCHA solved successfully")
                            return captcha_solution

                logger.error("Timeout waiting for CAPTCHA solution")
                return None

        except Exception as e:
            logger.error(f"Error solving CAPTCHA with Anti Captcha: {str(e)}")
            return None