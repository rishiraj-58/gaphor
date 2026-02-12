"""Template data structures for the diagram template system."""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple


class ParameterType(Enum):
    STRING = "string"
    INTEGER = "integer"
    BOOLEAN = "boolean"
    CHOICE = "choice"
    ELEMENT_REF = "element_ref"


@dataclass
class TemplateParameter:
    name: str
    param_type: ParameterType
    description: str = ""
    default_value: Any = None
    required: bool = True
    choices: List[str] = field(default_factory=list)
    placeholder_pattern: str = ""

    def __post_init__(self):
        if not self.placeholder_pattern:
            self.placeholder_pattern = f"${{{self.name}}}"

    def validate_value(self, value: Any) -> Tuple[bool, str]:
        if value is None or value == "":
            if self.required:
                return False, f"Parameter '{self.name}' is required"
            return True, ""

        if self.param_type == ParameterType.STRING:
            if not isinstance(value, str):
                return False, f"Parameter '{self.name}' must be a string"

        elif self.param_type == ParameterType.INTEGER:
            try:
                int(value)
            except (ValueError, TypeError):
                return False, f"Parameter '{self.name}' must be an integer"

        elif self.param_type == ParameterType.BOOLEAN:
            if not isinstance(value, bool) and value not in ("true", "false", "True", "False", "0", "1"):
                return False, f"Parameter '{self.name}' must be a boolean"

        elif self.param_type == ParameterType.CHOICE:
            if value not in self.choices:
                return False, f"Parameter '{self.name}' must be one of: {', '.join(self.choices)}"

        return True, ""


@dataclass
class TemplateCategory:
    id: str
    name: str
    description: str = ""
    icon: str = "folder-symbolic"
    parent_id: Optional[str] = None

    @classmethod
    def builtin_categories(cls) -> List[TemplateCategory]:
        return [
            cls(id="uml", name="UML", description="UML diagram templates", icon="UML"),
            cls(id="sysml", name="SysML", description="SysML diagram templates", icon="SysML"),
            cls(id="c4model", name="C4 Model", description="C4 architecture templates", icon="C4Model"),
            cls(id="raaml", name="RAAML", description="Risk analysis templates", icon="RAAML"),
            cls(id="patterns", name="Design Patterns", description="Common design pattern templates"),
            cls(id="custom", name="Custom", description="User-created templates"),
        ]


@dataclass
class DiagramTemplate:
    id: str
    name: str
    description: str
    category_id: str
    content: str
    parameters: List[TemplateParameter] = field(default_factory=list)
    tags: List[str] = field(default_factory=list)
    modeling_language: str = "UML"
    thumbnail_data: Optional[bytes] = None
    author: str = ""
    version: str = "1.0"
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
    required_elements: List[str] = field(default_factory=list)

    @classmethod
    def create_new(
        cls,
        name: str,
        description: str,
        category_id: str,
        content: str,
        modeling_language: str = "UML",
    ) -> DiagramTemplate:
        return cls(
            id=str(uuid.uuid4()),
            name=name,
            description=description,
            category_id=category_id,
            content=content,
            modeling_language=modeling_language,
        )

    def extract_parameters(self) -> List[TemplateParameter]:
        pattern = r'\$\{([a-zA-Z_][a-zA-Z0-9_]*)\}'
        matches = re.findall(pattern, self.content)
        param_names = list(dict.fromkeys(matches))

        existing_names = {p.name for p in self.parameters}
        new_params = []

        for name in param_names:
            if name not in existing_names:
                new_params.append(TemplateParameter(
                    name=name,
                    param_type=ParameterType.STRING,
                    description=f"Value for {name}",
                ))

        return self.parameters + new_params

    def apply_parameters(self, values: Dict[str, Any]) -> str:
        result = self.content
        for param in self.parameters:
            value = values.get(param.name, param.default_value)
            if value is not None:
                result = result.replace(param.placeholder_pattern, str(value))
        return result

    def get_search_text(self) -> str:
        return f"{self.name} {self.description} {' '.join(self.tags)}".lower()

    def matches_search(self, query: str) -> bool:
        if not query:
            return True
        search_text = self.get_search_text()
        return all(term.lower() in search_text for term in query.split())

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "category_id": self.category_id,
            "content": self.content,
            "parameters": [
                {
                    "name": p.name,
                    "param_type": p.param_type.value,
                    "description": p.description,
                    "default_value": p.default_value,
                    "required": p.required,
                    "choices": p.choices,
                    "placeholder_pattern": p.placeholder_pattern,
                }
                for p in self.parameters
            ],
            "tags": self.tags,
            "modeling_language": self.modeling_language,
            "author": self.author,
            "version": self.version,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "required_elements": self.required_elements,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> DiagramTemplate:
        parameters = [
            TemplateParameter(
                name=p["name"],
                param_type=ParameterType(p["param_type"]),
                description=p.get("description", ""),
                default_value=p.get("default_value"),
                required=p.get("required", True),
                choices=p.get("choices", []),
                placeholder_pattern=p.get("placeholder_pattern", ""),
            )
            for p in data.get("parameters", [])
        ]

        created_at = data.get("created_at")
        if isinstance(created_at, str):
            created_at = datetime.fromisoformat(created_at)
        elif created_at is None:
            created_at = datetime.now()

        updated_at = data.get("updated_at")
        if isinstance(updated_at, str):
            updated_at = datetime.fromisoformat(updated_at)
        elif updated_at is None:
            updated_at = datetime.now()

        return cls(
            id=data["id"],
            name=data["name"],
            description=data.get("description", ""),
            category_id=data["category_id"],
            content=data["content"],
            parameters=parameters,
            tags=data.get("tags", []),
            modeling_language=data.get("modeling_language", "UML"),
            author=data.get("author", ""),
            version=data.get("version", "1.0"),
            created_at=created_at,
            updated_at=updated_at,
            required_elements=data.get("required_elements", []),
        )
