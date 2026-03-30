"""
LLM Client — Unified interface for OpenAI, Vertex AI (Gemini), and Azure OpenAI.
Provides prompt-based analysis for the Debug and Fix agents.
"""
import os
import json
import logging
from typing import Optional

logger = logging.getLogger(__name__)


class LLMClient:
    """
    Unified LLM client that supports multiple providers:
      - openai  (OpenAI GPT-4 / GPT-3.5)
      - vertex_ai  (Google Vertex AI / Gemini)
      - azure_openai  (Azure-hosted OpenAI)
    """

    def __init__(self, config: dict):
        """
        Args:
            config: LLM section from config.yaml, e.g.:
                {
                    "provider": "openai",
                    "model": "gpt-4",
                    "temperature": 0.2,
                    "max_tokens": 4096,
                    "api_key_env": "OPENAI_API_KEY",
                    ...
                }
        """
        self.provider = config.get("provider", "openai")
        self.model = config.get("model", "gpt-4")
        self.temperature = config.get("temperature", 0.2)
        self.max_tokens = config.get("max_tokens", 4096)
        self.api_key_env = config.get("api_key_env", "")
        self.project_id = config.get("project_id", "")
        self.location = config.get("location", "us-central1")
        self.endpoint = config.get("endpoint", "")
        self.api_version = config.get("api_version", "")
        self._client = None

    def _init_openai(self):
        """Initialize OpenAI client."""
        try:
            import openai
            api_key = os.environ.get(self.api_key_env, "")
            if not api_key:
                raise ValueError(f"Environment variable {self.api_key_env} not set")
            self._client = openai.OpenAI(api_key=api_key)
            logger.info("OpenAI client initialized (model=%s)", self.model)
        except ImportError:
            raise ImportError("openai package not installed. Run: pip install openai")

    def _init_vertex_ai(self):
        """Initialize Vertex AI (Gemini) client."""
        try:
            import vertexai
            from vertexai.generative_models import GenerativeModel
            vertexai.init(project=self.project_id, location=self.location)
            self._client = GenerativeModel(self.model)
            logger.info("Vertex AI client initialized (model=%s, project=%s)", self.model, self.project_id)
        except ImportError:
            raise ImportError("google-cloud-aiplatform not installed. Run: pip install google-cloud-aiplatform")

    def _init_azure_openai(self):
        """Initialize Azure OpenAI client."""
        try:
            import openai
            api_key = os.environ.get(self.api_key_env, "")
            if not api_key:
                raise ValueError(f"Environment variable {self.api_key_env} not set")
            self._client = openai.AzureOpenAI(
                api_key=api_key,
                api_version=self.api_version,
                azure_endpoint=self.endpoint,
            )
            logger.info("Azure OpenAI client initialized (model=%s)", self.model)
        except ImportError:
            raise ImportError("openai package not installed. Run: pip install openai")

    def _ensure_client(self):
        """Lazy-initialize the client on first use."""
        if self._client is not None:
            return
        init_map = {
            "openai": self._init_openai,
            "vertex_ai": self._init_vertex_ai,
            "azure_openai": self._init_azure_openai,
        }
        init_fn = init_map.get(self.provider)
        if not init_fn:
            raise ValueError(f"Unsupported LLM provider: {self.provider}")
        init_fn()

    def analyze(self, prompt: str, system_prompt: Optional[str] = None) -> str:
        """
        Send a prompt to the LLM and return the response text.

        Args:
            prompt: The user/analysis prompt
            system_prompt: Optional system-level instruction

        Returns:
            Response text from the LLM
        """
        self._ensure_client()

        if self.provider in ("openai", "azure_openai"):
            return self._call_openai(prompt, system_prompt)
        elif self.provider == "vertex_ai":
            return self._call_vertex_ai(prompt, system_prompt)
        else:
            raise ValueError(f"Unsupported provider: {self.provider}")

    def analyze_json(self, prompt: str, system_prompt: Optional[str] = None) -> dict:
        """
        Send a prompt and parse the response as JSON.

        Args:
            prompt: The user/analysis prompt
            system_prompt: Optional system-level instruction

        Returns:
            Parsed JSON dict from the LLM response
        """
        raw = self.analyze(prompt, system_prompt)
        # Try to extract JSON from markdown code blocks
        if "```json" in raw:
            start = raw.index("```json") + 7
            end = raw.index("```", start)
            raw = raw[start:end].strip()
        elif "```" in raw:
            start = raw.index("```") + 3
            end = raw.index("```", start)
            raw = raw[start:end].strip()
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            logger.warning("Failed to parse LLM response as JSON, returning raw text")
            return {"raw_response": raw}

    def _call_openai(self, prompt: str, system_prompt: Optional[str] = None) -> str:
        """Call OpenAI / Azure OpenAI chat completions."""
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        response = self._client.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=self.temperature,
            max_tokens=self.max_tokens,
        )
        return response.choices[0].message.content

    def _call_vertex_ai(self, prompt: str, system_prompt: Optional[str] = None) -> str:
        """Call Vertex AI Gemini generateContent."""
        from vertexai.generative_models import GenerationConfig

        full_prompt = f"{system_prompt}\n\n{prompt}" if system_prompt else prompt
        response = self._client.generate_content(
            full_prompt,
            generation_config=GenerationConfig(
                temperature=self.temperature,
                max_output_tokens=self.max_tokens,
            ),
        )
        return response.text

    @staticmethod
    def load_prompt_template(template_path: str, **kwargs) -> str:
        """
        Load a prompt template file and substitute placeholders.

        Args:
            template_path: Path to .txt prompt template
            **kwargs: key=value pairs to substitute in the template

        Returns:
            Formatted prompt string
        """
        with open(template_path, "r", encoding="utf-8") as f:
            template = f.read()
        for key, value in kwargs.items():
            template = template.replace(f"{{{{{key}}}}}", str(value))
        return template

    def is_available(self) -> bool:
        """Check if the LLM client can be initialized (API key set, etc.)."""
        try:
            self._ensure_client()
            return True
        except Exception as e:
            logger.debug("LLM client not available: %s", e)
            return False
