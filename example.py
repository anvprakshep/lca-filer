#!/usr/bin/env python3
import os
import asyncio
import argparse
import json
from typing import Dict, Any

from lca_filer import LCAFiler
from utils.file_utils import FileUtils
from utils.logger import get_logger
from utils.authenticator import TwoFactorAuth

logger = get_logger(__name__)


async def file_lca_with_dol_mfa() -> None:
    """Example of filing an LCA with DOL's MFA secret."""
    # Get the DOL TOTP secret from environment variable
    dol_totp_secret = os.environ.get("DOL_TOTP_SECRET")
    if not dol_totp_secret:
        print("ERROR: DOL_TOTP_SECRET environment variable must be set")
        print("This is the secret key provided by DOL during MFA setup, not a QR code")
        print("Example: export DOL_TOTP_SECRET=ABCDEFGHIJKLMNOP")
        return

    username = os.environ.get("FLAG_USERNAME")
    password = os.environ.get("FLAG_PASSWORD")

    if not username or not password:
        print("ERROR: FLAG_USERNAME and FLAG_PASSWORD environment variables must be set")
        print("Example: export FLAG_USERNAME=your_username")
        print("         export FLAG_PASSWORD=your_password")
        return

    # Create a sample application
    application = {
        "id": "totp_example_app_001",
        "credentials": {
            "username": username,
            "password": password,
            "totp_secret": dol_totp_secret  # Include the TOTP secret in credentials
        },
        "employer": {
            "name": "Tech Solutions Inc.",
            "fein": "123456789",
            "naics": "541512",
            "address": "123 Main St",
            "city": "San Francisco",
            "state": "CA",
            "zip": "94105",
            "phone": "4155551234",
            "email": "hr@techsolutions.com"
        },
        "job": {
            "title": "Software Engineer",
            "soc_code": "15-1132",
            "duties": "Design, develop, and maintain software applications...",
            "requirements": "Bachelor's degree in Computer Science or related field..."
        },
        "wages": {
            "rate": "120000",
            "rate_type": "year",
            "prevailing_wage": "110000",
            "pw_source": "OES"
        },
        "worksite": {
            "address": "456 Market St",
            "city": "San Francisco",
            "state": "CA",
            "zip": "94105",
            "county": "San Francisco"
        },
        "foreign_worker": {
            "name": "John Smith",
            "birth_country": "India",
            "citizenship": "India",
            "education": "Master's Degree"
        }
    }

    # Initialize the LCA filer
    lca_filer = LCAFiler()

    try:
        # Initialize components
        logger.info("Initializing LCA filer")
        if not await lca_filer.initialize():
            logger.error("Failed to initialize LCA filer")
            return

        # Add the TOTP secret to the configuration if provided in application data
        if "totp_secret" in application["credentials"]:
            # Get username and TOTP secret
            app_username = application["credentials"]["username"]
            app_totp_secret = application["credentials"]["totp_secret"]

            # Add to configuration
            lca_filer.config.set_totp_secret(app_username, app_totp_secret)
            logger.info(f"Added DOL TOTP secret for {app_username} from application data")

            # Test the TOTP secret to make sure it generates codes
            if lca_filer.two_factor_auth:
                test_code = lca_filer.two_factor_auth.generate_totp_code(app_username)
                logger.info(f"Current TOTP code for testing: {test_code}")

        # Process the application
        logger.info("Processing application with DOL MFA authentication")
        result = await lca_filer.file_lca(application)

        # Print result
        logger.info(f"Processing complete. Status: {result['status']}")
        if result['status'] == 'success':
            logger.info(f"Confirmation number: {result.get('confirmation_number', 'N/A')}")
        else:
            logger.error(f"Error: {result.get('error', 'Unknown error')}")

    except Exception as e:
        logger.error(f"Error in processing: {str(e)}")
    finally:
        # Clean up resources
        logger.info("Shutting down LCA filer")
        await lca_filer.shutdown()


async def test_mfa_code() -> None:
    """Simple utility to test MFA code generation."""
    # Get the DOL TOTP secret from environment variable
    dol_totp_secret = os.environ.get("DOL_TOTP_SECRET")
    if not dol_totp_secret:
        print("ERROR: DOL_TOTP_SECRET environment variable must be set")
        print("This is the secret key provided by DOL during MFA setup, not a QR code")
        print("Example: export DOL_TOTP_SECRET=ABCDEFGHIJKLMNOP")
        return

    username = os.environ.get("FLAG_USERNAME", "test_user")

    print(f"\nTesting TOTP code generation for DOL secret...")

    # Create a test TOTP handler with the DOL secret
    config = {
        "secrets": {username: dol_totp_secret},
        "digits": 6,
        "interval": 30,
        "algorithm": "SHA1"
    }
    two_factor_auth = TwoFactorAuth(config)

    # Test the secret with different settings
    test_results = {
        "Default (SHA1, 6 digits, 30 sec)": two_factor_auth.test_secret(dol_totp_secret)
    }

    # Try with different algorithms in case DOL uses a different one
    for algorithm in ["SHA256", "SHA512"]:
        two_factor_auth.algorithm = algorithm
        two_factor_auth.config["algorithm"] = algorithm
        test_results[f"Using {algorithm}"] = two_factor_auth.test_secret(dol_totp_secret)

    # Try with different digit lengths
    for digits in [6, 8]:
        two_factor_auth.digits = digits
        two_factor_auth.config["digits"] = digits
        two_factor_auth.algorithm = "SHA1"  # Reset algorithm
        two_factor_auth.config["algorithm"] = "SHA1"
        test_results[f"Using {digits} digits"] = two_factor_auth.test_secret(dol_totp_secret)

    # Display results
    print("\n===== TOTP Code Test Results =====")
    for test_name, result in test_results.items():
        if result["valid"]:
            remaining = result.get("remaining_seconds", 0)
            print(f"✅ {test_name}:")
            print(f"   Code: {result['current_code']}")
            print(f"   Expires in: {remaining} seconds")
        else:
            print(f"❌ {test_name}: {result.get('error', 'Invalid secret')}")

    # Generate a sequence of codes and timing to help debug timing issues
    print("\n===== Code Sequence (Default settings) =====")
    two_factor_auth.digits = 6
    two_factor_auth.config["digits"] = 6
    two_factor_auth.algorithm = "SHA1"
    two_factor_auth.config["algorithm"] = "SHA1"

    # Get current time
    import time
    current_time = int(time.time())
    interval = 30

    print(f"Current time: {current_time}")
    print(f"Time mod {interval}: {current_time % interval}")
    print(f"Seconds until next code: {interval - (current_time % interval)}")

    # Calculate 3 consecutive codes
    for i in range(3):
        timestamp = current_time + (i * interval)
        code = _generate_totp_at_timestamp(dol_totp_secret, timestamp)
        valid_from = timestamp - (timestamp % interval)
        valid_until = valid_from + interval
        print(f"Code {i + 1}: {code} (valid from {valid_from} to {valid_until})")


def _generate_totp_at_timestamp(secret: str, timestamp: int) -> str:
    """
    Generate a TOTP code at a specific timestamp.

    Args:
        secret: TOTP secret
        timestamp: Unix timestamp

    Returns:
        TOTP code
    """
    import pyotp

    # Clean up the secret
    secret = ''.join(c for c in secret if c.isalnum())

    # Create TOTP object
    totp = pyotp.TOTP(secret)

    # Generate code at specific timestamp
    return totp.at(timestamp)


async def main() -> None:
    """Main function to run examples."""
    parser = argparse.ArgumentParser(description="H-1B LCA Filing with DOL MFA Examples")
    parser.add_argument("--example", choices=["file", "test"],
                        default="test", help="Which example to run")
    args = parser.parse_args()

    if args.example == "file":
        await file_lca_with_dol_mfa()
    elif args.example == "test":
        await test_mfa_code()


if __name__ == "__main__":
    # Check for required environment variables
    if not os.environ.get("OPENAI_API_KEY") and not os.environ.get("DOL_TOTP_SECRET"):
        print("ERROR: Either OPENAI_API_KEY (for filing) or DOL_TOTP_SECRET (for testing) must be set")
        exit(1)

    asyncio.run(main())