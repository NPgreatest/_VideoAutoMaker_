from typing import Dict, Type

class BaseMethod:  # minimal import-safe placeholder (real one is in methods/base.py)
    NAME: str = "Base"
    OUTPUT_KIND: str = "unknown"

_registry: Dict[str, type] = {}

def register_method(cls: Type[BaseMethod]):
    name = getattr(cls, "NAME", None)
    if not name:
        raise ValueError("Method class must define NAME")
    key = name.strip()
    if key in _registry:
        raise ValueError(f"Method '{key}' already registered")
    _registry[key] = cls
    return cls

def get_method(name: str):
    return _registry.get(name)

def list_methods():
    return sorted(_registry.keys())
