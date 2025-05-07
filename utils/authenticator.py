# utils/authenticator.py
import pyotp
import time
from typing import Dict, Any, Optional

from utils.logger import get_logger

logger = get_logger(__name__)


class TwoFactorAuth:
    """Handles two-factor authentication for the FLAG portal."""

    def __init__(self, config: Dict[str, Any]):
        """
        Initialize two-factor authentication.

        Args:
            config: Configuration dictionary with TOTP settings
        """
        self.config = config

        # Extract TOTP settings
        self.totp_secrets = self.config.get("secrets", {})
        self.digits = self.config.get("digits", 6)
        self.interval = self.config.get("interval", 30)
        self.algorithm = self.config.get("algorithm", "SHA1")

        logger.info(f"TwoFactorAuth initialized with {len(self.totp_secrets)} secrets")

    def generate_totp_code(self, username: str) -> Optional[str]:
        """
        Generate a TOTP code for the given username using stored secret.

        Args:
            username: Username to generate code for

        Returns:
            TOTP code or None if secret not found
        """
        secret = self.totp_secrets.get(username)
        if not secret:
            logger.error(f"TOTP secret not found for username: {username}")
            return None

        try:
            # Clean up the secret in case it has spaces or other formatting
            secret = self._clean_secret(secret)

            # Create TOTP object with the correct parameters
            totp = pyotp.TOTP(
                secret,
                digits=self.digits,
                interval=self.interval,
                digest=self._get_digest_algorithm()
            )

            # Generate the current code
            code = totp.now()
            logger.info(f"Generated TOTP code for {username}")
            return code

        except Exception as e:
            logger.error(f"Error generating TOTP code: {str(e)}")
            return None

    def get_remaining_seconds(self, username: str) -> Optional[int]:
        """
        Get remaining seconds until the current TOTP code expires.

        Args:
            username: Username to check

        Returns:
            Seconds remaining or None if secret not found
        """
        secret = self.totp_secrets.get(username)
        if not secret:
            logger.error(f"TOTP secret not found for username: {username}")
            return None

        try:
            # Clean up the secret
            secret = self._clean_secret(secret)

            # Create TOTP object
            totp = pyotp.TOTP(
                secret,
                digits=self.digits,
                interval=self.interval,
                digest=self._get_digest_algorithm()
            )

            # Calculate remaining seconds
            remaining = totp.interval - (int(time.time()) % totp.interval)
            return remaining

        except Exception as e:
            logger.error(f"Error calculating remaining time: {str(e)}")
            return None

    def verify_totp_code(self, username: str, code: str) -> bool:
        """
        Verify a TOTP code for the given username.

        Args:
            username: Username to verify code for
            code: TOTP code to verify

        Returns:
            True if code is valid, False otherwise
        """
        secret = self.totp_secrets.get(username)
        if not secret:
            logger.error(f"TOTP secret not found for username: {username}")
            return False

        try:
            # Clean up the secret
            secret = self._clean_secret(secret)

            # Create TOTP object
            totp = pyotp.TOTP(
                secret,
                digits=self.digits,
                interval=self.interval,
                digest=self._get_digest_algorithm()
            )

            # Verify the code
            is_valid = totp.verify(code)
            return is_valid

        except Exception as e:
            logger.error(f"Error verifying TOTP code: {str(e)}")
            return False

    def test_secret(self, secret: str) -> Dict[str, Any]:
        """
        Test a TOTP secret to make sure it generates valid codes.

        Args:
            secret: TOTP secret to test

        Returns:
            Dictionary with test results
        """
        try:
            # Clean up the secret
            secret = self._clean_secret(secret)

            # Create TOTP object
            totp = pyotp.TOTP(
                secret,
                digits=self.digits,
                interval=self.interval,
                digest=self._get_digest_algorithm()
            )

            # Generate current code
            code = totp.now()

            # Calculate remaining seconds
            remaining = totp.interval - (int(time.time()) % totp.interval)

            return {
                "valid": True,
                "current_code": code,
                "remaining_seconds": remaining,
                "digits": self.digits,
                "interval": self.interval,
                "algorithm": self.algorithm
            }

        except Exception as e:
            logger.error(f"Error testing TOTP secret: {str(e)}")
            return {
                "valid": False,
                "error": str(e)
            }

    def _clean_secret(self, secret: str) -> str:
        """
        Clean up a TOTP secret by removing spaces and formatting.

        Args:
            secret: TOTP secret to clean

        Returns:
            Cleaned secret
        """
        # Remove spaces and non-alphanumeric characters
        secret = ''.join(c for c in secret if c.isalnum())
        return secret

    def _get_digest_algorithm(self) -> str:
        """
        Get the digest algorithm for TOTP.

        Returns:
            Digest algorithm name for hashlib
        """
        algorithm = self.algorithm.upper()
        if algorithm == "SHA1":
            return "sha1"
        elif algorithm == "SHA256":
            return "sha256"
        elif algorithm == "SHA512":
            return "sha512"
        else:
            logger.warning(f"Unsupported algorithm: {algorithm}, using SHA1")
            return "sha1"

    def test_totp_for_user(self, username: str) -> Dict[str, Any]:
        """
        Test TOTP generation for a specific user and provide detailed diagnostic info.

        Args:
            username: Username to test TOTP for

        Returns:
            Dictionary with test results and diagnostics
        """
        results = {
            "username": username,
            "status": "failed",
            "error": "",
            "diagnostics": {}
        }

        try:
            # Check if we have a secret for this user
            secret = self.totp_secrets.get(username)
            if not secret:
                results["error"] = f"No TOTP secret found for username: {username}"
                return results

            # Try to clean the secret
            cleaned_secret = self._clean_secret(secret)
            results["diagnostics"]["original_secret"] = secret
            results["diagnostics"]["cleaned_secret"] = cleaned_secret
            results["diagnostics"]["secret_length"] = len(cleaned_secret)

            # Try with multiple algorithm combinations to diagnose issues
            algorithms = ["sha1", "sha256", "sha512"]
            digit_options = [6, 8]
            interval_options = [30, 60]

            all_test_results = {}

            # Try with default settings first
            try:
                totp = pyotp.TOTP(
                    cleaned_secret,
                    digits=self.digits,
                    interval=self.interval,
                    digest=self._get_digest_algorithm()
                )
                code = totp.now()
                remaining = self.interval - (int(time.time()) % self.interval)

                all_test_results["default"] = {
                    "algorithm": self.algorithm,
                    "digits": self.digits,
                    "interval": self.interval,
                    "code": code,
                    "remaining": remaining,
                    "success": True
                }
            except Exception as e:
                all_test_results["default"] = {
                    "algorithm": self.algorithm,
                    "digits": self.digits,
                    "interval": self.interval,
                    "error": str(e),
                    "success": False
                }

            # Try all combinations
            for alg in algorithms:
                for digits in digit_options:
                    for interval in interval_options:
                        key = f"{alg}_{digits}_{interval}"
                        try:
                            totp = pyotp.TOTP(
                                cleaned_secret,
                                digits=digits,
                                interval=interval,
                                digest=alg
                            )
                            code = totp.now()
                            remaining = interval - (int(time.time()) % interval)

                            all_test_results[key] = {
                                "algorithm": alg,
                                "digits": digits,
                                "interval": interval,
                                "code": code,
                                "remaining": remaining,
                                "success": True
                            }
                        except Exception as e:
                            all_test_results[key] = {
                                "algorithm": alg,
                                "digits": digits,
                                "interval": interval,
                                "error": str(e),
                                "success": False
                            }

            results["diagnostics"]["test_variations"] = all_test_results

            # If the default works, report success
            if all_test_results["default"]["success"]:
                results["status"] = "success"
                results["current_code"] = all_test_results["default"]["code"]
                results["remaining_seconds"] = all_test_results["default"]["remaining"]
            else:
                # Check if any configuration works
                working_configs = [k for k, v in all_test_results.items() if v["success"]]
                if working_configs:
                    best_config = working_configs[0]
                    results["status"] = "partial_success"
                    results["recommended_config"] = {
                        "algorithm": all_test_results[best_config]["algorithm"],
                        "digits": all_test_results[best_config]["digits"],
                        "interval": all_test_results[best_config]["interval"]
                    }
                    results["current_code"] = all_test_results[best_config]["code"]
                    results["error"] = f"Default configuration failed, but {best_config} works"
                else:
                    results["error"] = "Could not generate valid TOTP with any configuration"

        except Exception as e:
            results["error"] = f"Error testing TOTP: {str(e)}"

        return results