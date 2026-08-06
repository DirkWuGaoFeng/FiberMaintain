"""配置化 Skill 系统 — 声明式场景扩展机制。

将散落在 9 个文件中的扩展点收敛到单一 YAML Skill 文件。
新增场景 = 写 1 个 YAML，无需修改 Python 源码。
"""

from .schema import SkillDefinition
from .loader import SkillLoader, get_skill_loader

__all__ = ["SkillDefinition", "SkillLoader", "get_skill_loader"]
