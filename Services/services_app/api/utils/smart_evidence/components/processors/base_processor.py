from typing import Any, Dict, List, Optional
from smart_evidence.components import BaseComponent


class BaseProcessor(BaseComponent):
    def __init__(self, component: BaseComponent, **data: Any):
        super().__init__(component, **data)
        self.content_field: str = self.component_config.get("content_field", "text")

    @property
    def component(self) -> BaseComponent:
        """
        The Decorator delegates all work to the wrapped component.
        """

        return self._component

    def run(self, documents: List[Any], **kwds) -> List[Any]:
        raise NotImplementedError

    def evaluate(self, documents: List[Any], evaluations: Dict, **kwds) -> Any:
        raise NotImplementedError
