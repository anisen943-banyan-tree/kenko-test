from typing import Dict, List, Optional, Any
import yaml
import logging
import asyncio
from pydantic import BaseModel, ValidationError as PydanticValidationError
from openai import AsyncOpenAI
from tenacity import retry, stop_after_attempt, wait_exponential

class AssistantConfig(BaseModel):
    """Configuration for a single assistant."""
    model: str
    version: str
    timeout: int
    retry: Dict[str, int]
    instructions: str
    validation_rules: Dict[str, Any] = {}

class AssistantInitializationError(Exception):
    """Custom exception for assistant initialization errors."""
    def __init__(self, message: str, assistant_type: str, details: Optional[Dict] = None):
        super().__init__(message)
        self.assistant_type = assistant_type
        self.details = details or {}

class AssistantManager:
    """Manages the lifecycle and configuration of AI assistants."""
    
    def __init__(self, config_path: str, openai_client: AsyncOpenAI):
        self.config_path = config_path
        self.client = openai_client
        self.logger = logging.getLogger(__name__)
        self.assistants: Dict[str, str] = {}  # Maps assistant type to assistant ID
        self.configs: Dict[str, AssistantConfig] = {}
        
    async def initialize_assistants(self) -> Dict[str, str]:
        """Initialize all assistants defined in the configuration."""
        try:
            # Load configurations
            self.configs = await self._load_configs()
            
            # Initialize each assistant
            initialization_tasks = [
                self._initialize_single_assistant(assistant_type, config)
                for assistant_type, config in self.configs.items()
            ]
            
            # Wait for all initializations to complete
            results = await asyncio.gather(*initialization_tasks, return_exceptions=True)
            
            # Process results and handle any errors
            for assistant_type, result in zip(self.configs.keys(), results):
                if isinstance(result, Exception):
                    self.logger.error(
                        f"Failed to initialize {assistant_type} assistant: {str(result)}",
                        extra={"assistant_type": assistant_type, "config": self.configs[assistant_type].dict()}
                    )
                else:
                    self.assistants[assistant_type] = result
                    self.logger.info(
                        f"Successfully initialized {assistant_type} assistant",
                        extra={"assistant_type": assistant_type, "assistant_id": result}
                    )
            
            return self.assistants
            
        except Exception as e:
            self.logger.error(f"Assistant initialization failed: {str(e)}")
            raise AssistantInitializationError(
                "Failed to initialize assistants",
                "all",
                {"error": str(e)}
            )

    async def _load_configs(self) -> Dict[str, AssistantConfig]:
        """Load and validate assistant configurations from YAML."""
        try:
            with open(self.config_path, 'r') as f:
                raw_config = yaml.safe_load(f)

            configs = {}
            for assistant_type, config in raw_config['assistants'].items():
                try:
                    # Using pydantic to validate each assistant config
                    configs[assistant_type] = AssistantConfig(**config)
                except PydanticValidationError as e:
                    raise AssistantInitializationError(
                        f"Invalid configuration for {assistant_type} assistant",
                        "config",
                        {"assistant_type": assistant_type, "error": e.errors()}
                    )
            return configs

        except FileNotFoundError:
            raise AssistantInitializationError(
                "Configuration file not found",
                "config",
                {"config_path": self.config_path}
            )
        except yaml.YAMLError as e:
            raise AssistantInitializationError(
                "Error parsing YAML configuration",
                "config",
                {"error": str(e), "config_path": self.config_path}
            )
        except Exception as e:
            raise AssistantInitializationError(
                "Failed to load assistant configurations",
                "config",
                {"error": str(e), "config_path": self.config_path}
            )

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10)
    )
    async def _initialize_single_assistant(
        self,
        assistant_type: str,
        config: AssistantConfig
    ) -> str:
        """Initialize a single assistant with retry logic."""
        try:
            self.logger.info(f"Initializing {assistant_type} assistant", extra={"assistant_type": assistant_type})
            assistant = await self.client.beta.assistants.create(
                name=f"Claims {assistant_type.capitalize()} Assistant",
                instructions=config.instructions,
                model=config.model,
                tools=[{"type": "code_interpreter"}],
                metadata={
                    "version": config.version,
                    "type": assistant_type,
                    "timeout": str(config.timeout)
                }
            )
            
            self.logger.info(
                f"Successfully initialized {assistant_type} assistant",
                extra={"assistant_type": assistant_type, "assistant_id": assistant.id}
            )
            
            return assistant.id
            
        except Exception as e:
            self.logger.error(
                f"Failed to initialize {assistant_type} assistant",
                extra={"assistant_type": assistant_type, "config": config.dict(), "error": str(e)}
            )
            raise AssistantInitializationError(
                f"Failed to initialize {assistant_type} assistant",
                assistant_type,
                {
                    "error": str(e),
                    "config": config.dict()
                }
            )

    async def get_assistant(self, assistant_type: str) -> Optional[str]:
        """Get an assistant ID by type."""
        return self.assistants.get(assistant_type)

    async def cleanup(self):
        """Cleanup and delete all assistants."""
        cleaned_up_count = 0
        total_assistants = len(self.assistants)

        for assistant_type, assistant_id in self.assistants.items():
            try:
                await self.client.beta.assistants.delete(assistant_id)
                self.logger.info(
                    f"Cleaned up {assistant_type} assistant",
                    extra={"assistant_type": assistant_type, "assistant_id": assistant_id}
                )
                cleaned_up_count += 1
            except Exception as e:
                self.logger.error(
                    f"Failed to cleanup {assistant_type} assistant: {str(e)}",
                    extra={"assistant_type": assistant_type, "assistant_id": assistant_id}
                )

        self.logger.info(
            "Cleanup summary",
            extra={"total_assistants": total_assistants, "cleaned_up_count": cleaned_up_count}
        )

class AssistantFactory:
    """Factory for creating and managing assistant instances."""
    
    def __init__(self, openai_api_key: str, config_path: str):
        self.client = AsyncOpenAI(api_key=openai_api_key)
        self.manager = AssistantManager(config_path, self.client)
        
    async def __aenter__(self):
        """Initialize assistants when entering context."""
        await self.manager.initialize_assistants()
        return self.manager
        
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Cleanup assistants when exiting context."""
        await self.manager.cleanup()

# Usage example
async def initialize_assistants(config_path: str, openai_api_key: str):
    async with AssistantFactory(openai_api_key, config_path) as assistant_manager:
        try:
            # Get specific assistant
            categorization_assistant = await assistant_manager.get_assistant('categorization')
            
            # Use the assistant
            if categorization_assistant:
                # Process claims...
                pass
            else:
                logging.error("Categorization assistant not initialized")
        except Exception as e:
            logging.error(f"Error during assistant initialization: {str(e)}")

# Sample claim processing function
async def process_claims(assistant_manager: AssistantManager, claims: List[Dict[str, Any]]):
    categorization_assistant = await assistant_manager.get_assistant('categorization')
    if not categorization_assistant:
        raise ValueError("Categorization assistant not initialized")

    for claim in claims:
        # Example of using the assistant to process a claim
        result = await assistant_manager.client.beta.assistants.invoke(
            categorization_assistant,
            input=claim
        )
        print(f"Processed claim {claim['id']}: {result}")
