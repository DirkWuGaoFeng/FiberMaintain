from .base import Middleware, MiddlewareChain, RunContext
from .model_degradation import ModelDegradationMiddleware
from .domain_validation import FiberDomainValidationMiddleware
from .rag_injection import RAGInjectionMiddleware
from .audit_log import AuditLogMiddleware

def build_chain() -> MiddlewareChain:
    return MiddlewareChain([
        ModelDegradationMiddleware(),
        FiberDomainValidationMiddleware(),
        RAGInjectionMiddleware(),
        AuditLogMiddleware(),
    ])