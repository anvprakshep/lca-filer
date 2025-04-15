# config/config.py
import os
from typing import Dict, Any, Optional
import json
import yaml


class Config:
    """Configuration manager for LCA automation."""

    def __init__(self, config_path: Optional[str] = None):
        """
        Initialize configuration manager.

        Args:
            config_path: Path to configuration file (JSON or YAML)
        """
        self.config = self._load_default_config()

        if config_path:
            self._load_config_file(config_path)

        # Override with environment variables
        self._load_from_env()

    def _load_default_config(self) -> Dict[str, Any]:
        """Load default configuration."""
        return {
            "openai": {
                "api_key": "",
                "model": "gpt-4",
                "temperature": 0.1
            },
            "browser": {
                "headless": True,
                "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/96.0.4664.110 Safari/537.36",
                "viewport": {
                    "width": 1280,
                    "height": 800
                },
                "timeout": 60000  # 60 seconds
            },
            "flag_portal": {
                "url": "https://flag.dol.gov/",
                "credentials": {
                    "username": "",
                    "password": ""
                }
            },
            "processing": {
                "max_concurrent": 5,
                "max_retries": 3,
                "retry_delay": 5  # seconds
            },
            "captcha": {
                "service": "none",  # "none", "2captcha", "anticaptcha"
                "api_key": ""
            },
            "totp": {
                "enabled": False,
                "secrets": {},  # Map usernames to secrets
                "issuer": "LCA_Automation"
            },
            "output": {
                "results_dir": "data/results",
                "log_dir": "logs"
            }
        }

    def _load_config_file(self, config_path: str) -> None:
        """
        Load configuration from file.

        Args:
            config_path: Path to configuration file
        """
        if not os.path.exists(config_path):
            raise FileNotFoundError(f"Configuration file not found: {config_path}")

        file_ext = os.path.splitext(config_path)[1].lower()

        try:
            if file_ext == ".json":
                with open(config_path, "r") as f:
                    file_config = json.load(f)
            elif file_ext in [".yaml", ".yml"]:
                with open(config_path, "r") as f:
                    file_config = yaml.safe_load(f)
            else:
                raise ValueError(f"Unsupported configuration file format: {file_ext}")

            # Update config with file values
            self._update_nested_dict(self.config, file_config)

        except Exception as e:
            raise ValueError(f"Error loading configuration file: {str(e)}")

    def _load_from_env(self) -> None:
        """Load configuration from environment variables."""
        # Map of environment variables to config keys
        env_mapping = {
            "OPENAI_API_KEY": ["openai", "api_key"],
            "OPENAI_MODEL": ["openai", "model"],
            "BROWSER_HEADLESS": ["browser", "headless"],
            "FLAG_URL": ["flag_portal", "url"],
            "FLAG_USERNAME": ["flag_portal", "credentials", "username"],
            "FLAG_PASSWORD": ["flag_portal", "credentials", "password"],
            "MAX_CONCURRENT": ["processing", "max_concurrent"],
            "CAPTCHA_SERVICE": ["captcha", "service"],
            "CAPTCHA_API_KEY": ["captcha", "api_key"],
            "TOTP_ENABLED": ["totp", "enabled"],
            "TOTP_SECRET": ["totp", "secret"],
            "RESULTS_DIR": ["output", "results_dir"],
            "LOG_DIR": ["output", "log_dir"]
        }

        for env_var, config_path in env_mapping.items():
            if env_var in os.environ:
                # Special handling for boolean values
                if env_var == "BROWSER_HEADLESS" or env_var == "TOTP_ENABLED":
                    value = os.environ[env_var].lower() in ["true", "1", "yes"]
                # Special handling for integer values
                elif env_var == "MAX_CONCURRENT":
                    value = int(os.environ[env_var])
                else:
                    value = os.environ[env_var]

                # Set the value in the nested config
                self._set_nested_value(self.config, config_path, value)

        # Special handling for TOTP secrets from environment variables
        # Format: TOTP_SECRET_USERNAME=secretvalue
        for env_var, value in os.environ.items():
            if env_var.startswith("TOTP_SECRET_") and len(env_var) > 12:
                username = env_var[12:]
                if username:
                    self.config["totp"]["secrets"][username] = value

    def _update_nested_dict(self, d: Dict[str, Any], u: Dict[str, Any]) -> None:
        """
        Update nested dictionary recursively.

        Args:
            d: Target dictionary
            u: Source dictionary with updates
        """
        for k, v in u.items():
            if isinstance(v, dict) and k in d and isinstance(d[k], dict):
                self._update_nested_dict(d[k], v)
            else:
                d[k] = v

    def _set_nested_value(self, d: Dict[str, Any], path: list, value: Any) -> None:
        """
        Set value in nested dictionary using path.

        Args:
            d: Target dictionary
            path: List of keys forming path to target
            value: Value to set
        """
        for key in path[:-1]:
            d = d.setdefault(key, {})
        d[path[-1]] = value

    def get(self, *keys: str, default: Any = None) -> Any:
        """
        Get configuration value using dot notation.

        Args:
            *keys: Key path in config
            default: Default value if path doesn't exist

        Returns:
            Configuration value or default
        """
        current = self.config
        for key in keys:
            if isinstance(current, dict) and key in current:
                current = current[key]
            else:
                return default
        return current

    def set(self, value: Any, *keys: str) -> None:
        """
        Set configuration value using dot notation.

        Args:
            value: Value to set
            *keys: Key path in config
        """
        if not keys:
            return

        current = self.config
        for key in keys[:-1]:
            if key not in current:
                current[key] = {}
            current = current[key]

        current[keys[-1]] = value

    def save(self, config_path: str) -> None:
        """
        Save configuration to file.

        Args:
            config_path: Path to save configuration
        """
        print(f"\nConfiguration saved to {config_path}")
        # os.makedirs(os.path.dirname(config_path), exist_ok=True)

        file_ext = os.path.splitext(config_path)[1].lower()

        try:
            if file_ext == ".json":
                with open(config_path, "w") as f:
                    json.dump(self.config, f, indent=2)
            elif file_ext in [".yaml", ".yml"]:
                with open(config_path, "w") as f:
                    yaml.dump(self.config, f, default_flow_style=False)
            else:
                raise ValueError(f"Unsupported configuration file format: {file_ext}")
        except Exception as e:
            raise ValueError(f"Error saving configuration file: {str(e)}")

    def has_totp_secret(self, username: str) -> bool:
        """
        Check if TOTP secret exists for a username.

        Args:
            username: Username to check

        Returns:
            True if TOTP secret exists, False otherwise
        """
        totp_secrets = self.config.get("totp", {}).get("secrets", {})
        return username in totp_secrets

    def get_totp_secret(self, username: str) -> Optional[str]:
        """
        Get TOTP secret for a username.

        Args:
            username: Username to get secret for

        Returns:
            TOTP secret or None if not found
        """
        totp_secrets = self.config.get("totp", {}).get("secrets", {})
        return totp_secrets.get(username)

    def set_totp_secret(self, username: str, secret: str) -> None:
        """
        Set TOTP secret for a username.

        Args:
            username: Username to set secret for
            secret: TOTP secret
        """
        if "totp" not in self.config:
            self.config["totp"] = {}
        if "secrets" not in self.config["totp"]:
            self.config["totp"]["secrets"] = {}

        self.config["totp"]["secrets"][username] = secret

        # Enable TOTP if not already enabled
        self.config["totp"]["enabled"] = True