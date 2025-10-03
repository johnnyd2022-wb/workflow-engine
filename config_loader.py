import os
import configparser
from typing import Dict, Any

class Config:
    """Configuration loader for environment-specific settings"""
    
    def __init__(self):
        self.config = configparser.ConfigParser()
        self.environment = os.getenv('WB_ENVIRONMENT', 'local')
        self.load_config()
    
    def load_config(self):
        """Load configuration based on environment"""
        config_file = f'config/{self.environment}.ini'
        
        if not os.path.exists(config_file):
            raise FileNotFoundError(f"Configuration file {config_file} not found")
        
        self.config.read(config_file)
        print(f"✅ Loaded configuration for environment: {self.environment}")
    
    def get(self, section: str, key: str, fallback: Any = None) -> str:
        """Get a configuration value"""
        return self.config.get(section, key, fallback=fallback)
    
    def getboolean(self, section: str, key: str, fallback: bool = False) -> bool:
        """Get a boolean configuration value"""
        return self.config.getboolean(section, key, fallback=fallback)
    
    def getint(self, section: str, key: str, fallback: int = 0) -> int:
        """Get an integer configuration value"""
        return self.config.getint(section, key, fallback=fallback)
    
    @property
    def environment(self) -> str:
        return self._environment
    
    @environment.setter
    def environment(self, value: str):
        self._environment = value
    
    @property
    def debug(self) -> bool:
        return self.getboolean('app', 'debug', False)
    
    @property
    def host(self) -> str:
        return self.get('app', 'host', 'localhost')
    
    @property
    def port(self) -> int:
        return self.getint('app', 'port', 5000)
    
    @property
    def db_host(self) -> str:
        return self.get('database', 'host', 'localhost')
    
    @property
    def db_port(self) -> int:
        return self.getint('database', 'port', 5432)
    
    @property
    def db_name(self) -> str:
        return self.get('database', 'name', 'whistlebird_db')
    
    @property
    def db_user(self) -> str:
        return self.get('database', 'user', 'postgres')
    
    @property
    def db_password(self) -> str:
        return self.get('database', 'password', '')
    
    @property
    def xero_client_id(self) -> str:
        return self.get('xero', 'client_id', '')
    
    @property
    def xero_client_secret(self) -> str:
        return self.get('xero', 'client_secret', '')
    
    @property
    def sender_email(self) -> str:
        return self.get('email', 'sender_email', '')
    
    @property
    def receiver_email(self) -> str:
        return self.get('email', 'receiver_email', '')
    
    @property
    def invoice_button_enabled(self) -> bool:
        return self.getboolean('features', 'invoice_button_enabled', False)
    
    @property
    def schedule_enabled(self) -> bool:
        return self.getboolean('features', 'schedule_enabled', True)
    
    @property
    def docker_enabled(self) -> bool:
        return self.getboolean('docker', 'enabled', False)
    
    @property
    def docker_container_name(self) -> str:
        return self.get('docker', 'container_name', 'whistlebird_db')
    
    @property
    def docker_image_name(self) -> str:
        return self.get('docker', 'image_name', 'postgres')
    
    @property
    def docker_host_port(self) -> int:
        return self.getint('docker', 'host_port', 5432)
    
    @property
    def docker_container_port(self) -> int:
        return self.getint('docker', 'container_port', 5432)
    
    @property
    def crm_enabled(self) -> bool:
        return self.getboolean('features', 'crm_enabled', True)

# Global config instance
config = Config()
