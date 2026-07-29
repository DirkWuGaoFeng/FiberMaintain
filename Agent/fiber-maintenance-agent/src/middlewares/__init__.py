from .base import Middleware, MiddlewareChain, RunContext
from .rate_limit import RateLimitMiddleware, RateLimitExceeded
from .model_degradation import ModelDegradationMiddleware
from .domain_validation import FiberDomainValidationMiddleware
from .rag_injection import RAGInjectionMiddleware
from .output_verification import OutputVerificationMiddleware
from .audit_log import AuditLogMiddleware

def build_chain() -> MiddlewareChain:
    return MiddlewareChain([
        RateLimitMiddleware(),          # Phase 3.5: 令牌桶限流
        ModelDegradationMiddleware(),
        FiberDomainValidationMiddleware(),  # v3.3.0: 意图预分类 + 参数自纠正
        RAGInjectionMiddleware(),          # v3.3.0: 输入清洗 + Prompt 注入防护
        OutputVerificationMiddleware(),     # v3.3.0: 输出自检 + 数据一致性校验
        AuditLogMiddleware(),
    ])