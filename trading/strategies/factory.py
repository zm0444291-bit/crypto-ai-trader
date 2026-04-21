"""StrategyRegistry — central registration for all strategy classes.

Example
-------
registry = StrategyRegistry()
registry.register(MeanReversionStrategy)
registry.register(BreakoutStrategy)

strategy = registry.create("mean_reversion")
"""

from __future__ import annotations

from trading.strategies.active.breakout import BreakoutStrategy
from trading.strategies.active.mean_reversion import MeanReversionStrategy


class StrategyRegistry:
    """A simple in-memory registry for strategy classes.

    Supports both class registration (for runtime use) and instance creation
    via a factory method.
    """

    _registry: dict[str, type] = {}

    @classmethod
    def register(cls, strategy_cls: type) -> None:
        """Register a strategy class by its STRATEGY_NAME class variable."""
        name = getattr(strategy_cls, "STRATEGY_NAME", None)
        if name is None:
            raise ValueError(
                f"Strategy class {strategy_cls.__name__} must define "
                "STRATEGY_NAME as a class-level string constant."
            )
        cls._registry[name] = strategy_cls

    @classmethod
    def create(cls, name: str, **kwargs: object) -> object:
        """Instantiate a registered strategy by name with optional kwargs."""
        if name not in cls._registry:
            available = list(cls._registry.keys())
            raise KeyError(
                f"Unknown strategy '{name}'. Available strategies: {available}"
            )
        return cls._registry[name](**kwargs)

    @classmethod
    def list_strategies(cls) -> list[str]:
        """Return a sorted list of all registered strategy names."""
        return sorted(cls._registry.keys())

    @classmethod
    def is_registered(cls, name: str) -> bool:
        """Return True if the strategy name is registered."""
        return name in cls._registry


# Auto-register built-in strategies on module load
StrategyRegistry.register(MeanReversionStrategy)
StrategyRegistry.register(BreakoutStrategy)
