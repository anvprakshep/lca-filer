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